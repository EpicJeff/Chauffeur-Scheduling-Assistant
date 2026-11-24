// Roof envelope -> exposed downhill edges -> immutable GPU instances. All plan
// queries and downward rays happen on rebuild, never in update(). No lit patch.
import * as THREE from 'three';
import { roofMesh, planes } from '../twin_roof.js';
import { buildingBase, groundAt, inPolygon, segmentIntersection, poolDatum } from '../twin_ground.js';
import { allPorches } from '../twin_generator.js';
import { resolveSurfaceMaterial } from '../surface_material.js';
import { collectHardSurfaces } from './precipitation.js';
import { collectCapSurfaces, createCapSurfaceIndex } from './wet_caps.js';
import { gutterRuns, downspouts } from '../gutters.js';

const FT=.3048, EPS=2e-4;
const clamp=x=>Number.isFinite(x)?Math.max(0,Math.min(1,x)):0;
const smooth=(a,b,x)=>{const t=clamp((x-a)/(b-a));return t*t*(3-2*t);};
const LOD_NEAR=22,LOD_MID=54,LOD_FADE=95,LOD_FAR=120,LOD_FLOOR=.35,MIST_FAR=25;
const lodDensity=d=>(1-(1-LOD_FLOOR)*smooth(LOD_NEAR,LOD_MID,d))*(1-smooth(LOD_FADE,LOD_FAR,d));
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
          section:g.index,side:`${'xy'[g.axis]}${g.sign>0?1:0}`,edge:g.edge>=0?g.edge:null,kind:g.s.kind,gridStart:lo*FT,
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
            side:null,edge:null,kind:'attachment',gridStart:pitch===null?0:-pitch*.5,...pattern});
        }
      }
    }
  }
  return clipExposedEdges(result,frames,roofs);
}

export function clipExposedEdges(edges,frames,roofs) {
  return createEaveClipper(frames,roofs)(edges);
}

// Reuse the exact mesh/wall exposure query for rebuild-time endpoint probes.
// Stream extraction still invokes it once through clipExposedEdges above.
export function createEaveClipper(frames,roofs) {
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
  const ray=new THREE.Ray(new THREE.Vector3(),new THREE.Vector3(0,-1,0)),hit=new THREE.Vector3();
  return edges=>{
  const result=[];
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
  };
}

// Static down-rays against the actual triangulated roof envelope, plus the
// authored deck/paving and terrain receivers used by precipitation. The ray
// starts just outside the lip, so it cannot hit its own fascia/underside.
// Opt-in roofDetails adds roofEave in world metres for storey-aware drops;
// ordinary stream callers retain the same {height,kind} result and ray tests.
// Cap sources build/cache their exact tops on the first ray inside their bounds.
// lazyCaps:false retains eager collection for parity checks.
export function createEaveLandingSampler(plan={},roofs=new Map(),{roofDetails=false,lazyCaps=true}={}) {
  const triangles=[],decks=[],hard=collectHardSurfaces(plan);
  const caps=lazyCaps?null:collectCapSurfaces(plan);
  const capsAt=lazyCaps?createCapSurfaceIndex(plan):()=>caps;
  for(const b of plan.buildings||[]){
    const f=buildingFrame(plan,b),roof=roofs?.get(b.id)||roofMesh(b.roof?.sections||[]);
    // section[] indexes positions[], never the renderer's independently
    // ordered coverPositions. Placement uses that canonical mesh plus known
    // attachment geometry; ordinary stream rays retain their existing cover.
    const positions=[...(roofDetails?roof.positions:roof.coverPositions||roof.positions),
      ...(roofDetails?(roof.eaveAttachments||[]).flatMap(a=>Array.from(a.positions)):[]),...(roof.slabPositions||[])];
    const eaves=new Map();
    if(roofDetails)for(let t=0;t<roof.positions.length;t+=9){const section=roof.section?.[t/9];
      eaves.set(section,Math.min(eaves.get(section)??Infinity,...[2,5,8].map(i=>roof.positions[t+i])));}
    for(let t=0;t<positions.length;t+=9){
      const p=[0,3,6].map(i=>new THREE.Vector3(...f.world(positions.slice(t+i,t+i+3))));
      const eave=t<roof.positions.length?eaves.get(roof.section?.[t/9]):null;
      triangles.push({p,x0:Math.min(...p.map(v=>v.x)),x1:Math.max(...p.map(v=>v.x)),z0:Math.min(...p.map(v=>v.z)),z1:Math.max(...p.map(v=>v.z)),
        eave:eave==null?Math.min(...p.map(v=>v.y)):(f.base+eave)*FT});
    }
    for(const p of allPorches(b))if(p.polygon?.length>=3){
      const room=b.rooms?.find(r=>r.kind==='porch'&&r.level===(p.level||b.levels?.[0]?.id)&&inPolygon(r.polygon,...p.polygon[0]));
      decks.push({frame:f,polygon:p.polygon,height:(f.base+(p.floor||0)+(room?.floor_offset_ft||0))*FT});
    }
  }
  const ray=new THREE.Ray(new THREE.Vector3(),new THREE.Vector3(0,-1,0)),hit=new THREE.Vector3();
  return top=>{
    const [x,y,z]=top,px=x/FT,py=-z/FT;let height=groundAt(plan,px,py)*FT,kind='ground',roofEave=null;
    const offer=(h,k,eave=null)=>{if(h<y-.005&&h>=height){height=h;kind=k;roofEave=eave;}};
    for(const h of hard)if(inPolygon(h.polygon,px,py))offer(((h.flat??groundAt(plan,px,py))+h.elevation)*FT,'hardscape');
    for(const cap of capsAt(px,py,(y-.005)/FT))if(inPolygon(cap.polygon,px,py)&&!(cap.holes||[]).some(p=>inPolygon(p,px,py)))offer(cap.top*FT,'cap');
    for(const bed of plan.site?.beds||[])if(bed.polygon&&inPolygon(bed.polygon,px,py))offer((groundAt(plan,px,py)+(bed.elevation||0)+.12)*FT,'bed');
    const pool=plan.site?.pool;
    if(pool?.polygon&&inPolygon(pool.polygon,px,py))offer((poolDatum(plan,pool)-.25)*FT,'water');
    for(const d of decks){const p=d.frame.local(top);if(inPolygon(d.polygon,...p))offer(d.height,'deck');}
    ray.origin.set(x,y-.005,z);
    for(const t of triangles)if(x>=t.x0&&x<=t.x1&&z>=t.z0&&z<=t.z1
      &&ray.intersectTriangle(...t.p,false,hit))offer(hit.y,'roof',t.eave);
    return roofDetails&&kind==='roof'?{height,kind,roofEave}:{height,kind};
  };
}

export function eaveSheetCapable(e) {
  const length=Math.hypot(e.b[0]-e.a[0],e.b[2]-e.a[2]);
  if(length<.8||Math.abs(e.a[1]-e.b[1])>EPS)return 0;
  // Flat straight standing-seam metal pans can merge into a sheer-descent sheet
  // under heavy flow (strongest on flat straight wall awnings); corrugated
  // troughs (!pan && pitch) and rough/shingle edges (!pan) stay discrete streams.
  if(!e.pan)return 0;
  return e.kind==='attachment'?1:.75;
}

function planHasGutters(plan) {
  for (const b of plan?.buildings || []) {
    if ((b.roofs || []).some(r => (r.edges || []).some(e => e?.gutter === true))) return true;
    if ((b.roof?.sections || []).some(s => s.gutters && Object.values(s.gutters).some(v => v === true))) return true;
    if (allPorches(b).some(p => p?.gutter === true && p.state !== 'ghost' && p.state !== 'proposal')) return true;
    if ((b.roof?.extensions || []).some(e => e?.kind === 'awning' && e.gutter === true && e.state !== 'ghost' && e.state !== 'proposal')) return true;
  }
  return false;
}

function pointOnSegmentXZ(p, a, b) {
  const dx = b[0] - a[0], dz = b[2] - a[2], l2 = dx * dx + dz * dz;
  if (l2 < 1e-8) return Math.hypot(p[0] - a[0], p[2] - a[2]);
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[2] - a[2]) * dz) / l2));
  return Math.hypot(p[0] - (a[0] + dx * t), p[2] - (a[2] + dz * t));
}

function eaveIsGuttered(plan, roofs, e, runSegsByBuilding) {
  const segs = runSegsByBuilding.get(e.building) || [];
  const mid = [(e.a[0] + e.b[0]) * .5, (e.a[1] + e.b[1]) * .5, (e.a[2] + e.b[2]) * .5];
  for (const seg of segs) {
    if (Math.abs(mid[1] - (seg.a[1] + seg.b[1]) * .5) > .05) continue;
    if (pointOnSegmentXZ(mid, seg.a, seg.b) < .04 && pointOnSegmentXZ(e.a, seg.a, seg.b) < .05 && pointOnSegmentXZ(e.b, seg.a, seg.b) < .05)
      return true;
  }
  const b = (plan.buildings || []).find(v => v.id === e.building);
  if (!b) return false;
  const sections = roofs?.get(b.id)?.sections || b.roof?.sections || [];
  const s = sections[e.section];
  if (e.kind !== 'attachment' && s && e.side) {
    const rId = s.roof || s.id;
    const r = b.roofs?.find(v => v.id === rId);
    const edgeIdx = s.plane_edges ? s.plane_edges[e.side] : ['y0', 'x1', 'y1', 'x0'].indexOf(e.side);
    const rec = Number.isInteger(edgeIdx) ? r?.edges?.[edgeIdx] : null;
    if (rec && typeof rec.gutter === 'boolean') {
      if (rec.gutter === true && rec.setting === 'sloped') return true;
    } else if (s.gutters?.[e.side] === true) {
      return true;
    }
    const centre = [(s.rect[0] + s.rect[2]) * .5, (s.rect[1] + s.rect[3]) * .5];
    if (allPorches(b).some(p => p?.gutter === true && p.state !== 'ghost' && p.state !== 'proposal' && p.polygon?.length >= 3 && inPolygon(p.polygon, ...centre)))
      return true;
  }
  return false;
}

export const _eaveGutterStats = {
  fallbackCalls: 0,
  reset() { this.fallbackCalls = 0; },
};

export function eaveInstances(plan={},roofs=new Map(),kit={},gutters=null) {
  const rawEaves=extractEaves(plan,roofs,kit),sample=createEaveLandingSampler(plan,roofs),instances=[],pours=[];
  const hasGutters=gutters?(gutters.runs?.length>0||gutters.spouts?.length>0):planHasGutters(plan);
  let eaves=rawEaves;
  if(hasGutters){
    let runs,spouts;
    if(gutters){
      runs=gutters.runs||[];
      spouts=gutters.spouts||[];
    }else{
      _eaveGutterStats.fallbackCalls++;
      runs=gutterRuns(plan,roofs);
      spouts=runs.length?downspouts(plan,runs):[];
    }
    const runSegsByBuilding=new Map();
    for(const r of runs){
      if(!runSegsByBuilding.has(r.building))runSegsByBuilding.set(r.building,[]);
      runSegsByBuilding.get(r.building).push(...r.segments);
    }
    eaves=rawEaves.filter(e=>!eaveIsGuttered(plan,roofs,e,runSegsByBuilding));
    for(let idx=0;idx<spouts.length;idx++){
      const spout=spouts[idx];
      if(!spout?.outlet?.at)continue;
      const flags=spout.flags||[];
      const isBlocked=flags.includes('outlet-blocked');
      const isHang=spout.mount==='hang'||flags.includes('hang')||flags.includes('stub');
      const top=[...spout.outlet.at];
      const rawDir=spout.outlet.dir||[0,0,1],dirLen=Math.hypot(rawDir[0],rawDir[2])||1;
      const pourDir=[rawDir[0]/dirLen,0,rawDir[2]/dirLen];
      const share=clamp(spout.share??1);
      let bottom,pourForward;
      if(isBlocked){
        // Blocked gutter outlet jammed against a lower roof: short forward spill onto the receiving roof.
        pourForward=.30*FT;
        const hitAt=sample([top[0],top[1]+.08,top[2]]);
        const hitFwd=sample([top[0]+pourDir[0]*pourForward,top[1]+.08,top[2]+pourDir[2]*pourForward]);
        const surfaceY=Math.max(hitAt.height,hitFwd.height);
        const fall=Math.max(.08*FT,Math.min(.55*FT,top[1]-surfaceY));
        bottom=top[1]-fall;
      }else if(isHang){
        const hit=sample(top);
        bottom=Math.min(top[1]-.12,hit.height);
        pourForward=.04*FT;
      }else{
        // Pour leaves the curved elbow mouth along outlet.dir and lands shortly beyond the mouth (~0.4-0.6 ft from wall).
        const isRoof=spout.outlet.lands==='roof';
        const probeHit=sample([top[0]+pourDir[0]*.18*FT,top[1]+.05,top[2]+pourDir[2]*.18*FT]);
        const dropFt=isRoof&&probeHit.kind!=='roof'?4/12:Math.max(.20,Math.min(1.5,(top[1]-probeHit.height)/FT));
        pourForward=Math.max(.16,Math.min(.28,dropFt*.45))*FT;
        const hit=sample([top[0]+pourDir[0]*pourForward,top[1]+.05,top[2]+pourDir[2]*pourForward]);
        const fall=isRoof&&hit.kind!=='roof'?4/12*FT:Math.max(.20*FT,top[1]-hit.height);
        bottom=top[1]-fall;
      }
      if(top[1]-bottom<(isBlocked?.015:.05))continue;
      const pourWidth=.016+.028*share;
      const angle=Math.atan2(pourDir[2],pourDir[0]);
      const seed=hash(0x504f5552+idx*97+1);
      pours.push({top,bottom,landing:spout.outlet.lands||'ground',seed,rank:-1,
        eaveS:pourForward,cellStep:pourWidth,sheetCap:-Math.max(.05,share),angle,eave:null,
        pour:true,spout,share,mount:spout.mount,lands:spout.outlet.lands,pourDir,pourForward,pourWidth});
    }
  }
  let serial=1,eaveOffset=0;
  for(const e of eaves){
    const dx=e.b[0]-e.a[0],dz=e.b[2]-e.a[2],length=Math.hypot(dx,dz),n=Math.hypot(...e.outward);
    // A standing-seam pan sheds across its whole edge, not just at its seam.
    // Subdivide its actual pitch into ~9 cm cells, jittered within each pan.
    // Corrugated/exposed trough pitch stays exact. Unknown profiles reserve a
    // dense irregular curtain; GPU/instance-count thinning supplies light rain.
    const step=e.pan?e.pitch/Math.max(2,Math.ceil(e.pitch/.1)):e.pitch;
    const cellStep=step||.09;
    const sheetCap=eaveSheetCapable(e);
    const angle=Math.atan2(dz,dx);
    let grid=step?Math.ceil((e.gridStart+.0001)/step)*step-e.gridStart:.035+hash(serial)*.035;
    for(;grid<length-.02;grid+=step||(.065+.05*hash(++serial))){
      const distance=grid+(e.pan?(hash(serial+71)-.5)*step*.3:0);
      if(distance<=.015||distance>=length-.015){serial++;continue;}
      const u=distance/length,top=[e.a[0]+dx*u+e.outward[0]/n*.012,e.a[1],e.a[2]+dz*u+e.outward[2]/n*.012];
      const landing=sample(top);
      if(top[1]-landing.height<.08)continue;
      const seed=hash(++serial);
      instances.push({top,bottom:landing.height,landing:landing.kind,seed,rank:hash(serial+17389),
        eaveS:eaveOffset+distance,cellStep,sheetCap,angle,eave:e});
    }
    eaveOffset+=length+17.3;
  }
  // Prefix thinning removes actual vertex work on Low; hash order spreads it
  // over every edge rather than taking only the first side of the first house.
  // Activation order is independent of visual seed, so Low is not restricted
  // to the same thin/dim/early-phase streams.
  instances.sort((a,b)=>a.rank-b.rank);
  const allInstances=pours.length?[...pours,...instances]:instances;
  return {eaves,instances:allInstances,pours};
}

// Scalar shape functions are also exercised directly from the actual shader
// source by the Node regression tests; no separately maintained look model.
const waterShape=`
float eaveHash1(float p){
  float x=fract(p*.1031);
  x*=x+33.33;
  return fract(x*(x+x));
}
float eaveNoise1(float x){
  float i=floor(x),f=fract(x);
  return mix(eaveHash1(i),eaveHash1(i+1.),f*f*(3.-2.*f));
}
float eaveFallTime(float fall){
  // Free fall under g = 9.81 m/s^2 from roof-edge speed v0 = 0.45 m/s:
  // d(tau)/d(fall) = 1 / sqrt(v0^2 + 2*g*fall) -> advection speed = sqrt(0.2025 + 19.62*fall).
  // At fall = 1 m: v = 4.452 m/s vs sqrt(2*g*1) = 4.429 m/s (+0.5%).
  return (sqrt(.2025+19.62*max(fall,0.))-.45)/9.81;
}
float eaveActivity(float eaveS,float time,float seed,float flow){
  if(flow<=.002)return 0.;
  // Gathered roof-film lanes clump neighbouring outlets into heavier pours with quiet gaps
  // between them; incommensurate drift speeds prevent any visible repeat over 60+ seconds.
  float l1=abs(fract(eaveS*.72-time*.0483)*2.-1.);
  float l2=abs(fract(eaveS*.41+time*.0317+.31)*2.-1.);
  float l3=abs(fract(eaveS*.23-time*.0193+.67)*2.-1.);
  float lane=l1*.46+l2*.34+l3*.20;
  float clump=smoothstep(.26,.82,lane);
  // Per-site surge/decay cycle so streams form, run, thin, stop, and start elsewhere.
  float rate=.061+.083*fract(seed*23.17);
  float site=eaveNoise1(time*rate+seed*197.3);
  float supply=clump*.66+site*.34;
  float thresh=mix(.70,.46,flow);
  return smoothstep(thresh,thresh+.24,supply);
}
float eaveSheetAmount(float eaveS,float time,float flow,float sheetCap){
  if(sheetCap<=.01||flow<.62)return 0.;
  float s1=abs(fract(eaveS*.38-time*.055+.17)*2.-1.);
  float s2=abs(fract(eaveS*.83+time*.041+.63)*2.-1.);
  float surge=s1*.62+s2*.38;
  float heavy=smoothstep(.64,.96,flow)*sheetCap;
  return smoothstep(.52,.78,surge*heavy);
}
float eaveWidth(float fall,float time,float seed,float flow){
  float t=time-eaveFallTime(fall);
  float thickness=.35+1.85*fract(seed*31.73);
  float swell=.74+.52*eaveNoise1(t*11.3+seed*97.3);
  float outlet=1.+.65*(1.-smoothstep(0.,.85,fall));
  float neck=1.-smoothstep(.45,2.8,fall)*.32*(1.-flow*.40);
  return mix(.0045,.022,flow)*thickness*swell*outlet*neck;
}
float eaveWobble(float fall,float time,float seed){
  float t=time-eaveFallTime(fall);
  float n1=eaveNoise1(t*3.1+seed*73.1)-.5;
  float n2=abs(fract(t*3.9+seed*13.7)*2.-1.)-.5;
  return (n1*.034+n2*.014)*(1.+fall*.26);
}
float eavePresence(float fall,float fallLength,float time,float seed,float flow){
  float t=time-eaveFallTime(fall);
  float strength=fract(seed*19.19);
  if(flow<.24){
    float freq=.35+flow*4.5;
    float cycle=fract(t*freq+seed*17.3);
    float dropLen=.08+.12*flow;
    return 1.-smoothstep(dropLen*.45,dropLen,abs(cycle-.5));
  }
  float breakDist=mix(.35,1.65,flow)*(.55+.9*strength);
  float breakup=smoothstep(breakDist*.45,breakDist*1.45,fall);
  float n1=eaveNoise1(t*(5.8+3.6*strength)+seed*61.7);
  float n2=abs(fract(t*(7.1+3.1*strength)+seed*19.3)*2.-1.);
  float packet=n1*.65+n2*.35;
  float cut=mix(-.08,.62-flow*.14,breakup);
  float broken=smoothstep(cut,cut+.16,packet);
  return mix(1.,broken,breakup);
}
float eaveGlint(float fall,float time,float seed){
  float t=time-eaveFallTime(fall);
  float s1=eaveNoise1(t*18.5+seed*113.1);
  float s2=abs(fract(t*19.7+seed*27.9)*2.-1.);
  return smoothstep(.42,.95,s1*.68+s2*.32)*(.35+.65*fract(seed*47.13));
}
float eaveOpacity(float across,float glint,float flow){
  float q=abs(across);
  float ndv=sqrt(max(.08,1.-q*q));
  float f1=1.-ndv;
  float fresnel=.02+.98*f1*f1*f1*f1;
  // Clear cylindrical centre (water F0=0.02), Fresnel grazing edges & fast motion-blurred glints.
  return (.01+.25*fresnel+.055*glint)*(1.-smoothstep(.78,1.,q))*mix(.55,1.,flow);
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
float eaveSheetLumGain(float ripMod,float skyMix,float ripSpec,float sheetRim){
  // Falling clear sheet reflects bright overhead sky & glints with zero-mean
  // ripple modulation and bright tearing vertical strands; never darkens behind it.
  return max(1.02,1.10+.34*skyMix+1.05*ripSpec+.38*ripMod+.55*sheetRim);
}
float eaveSheetAlpha(float across,float fresnel,float ripSpec,float ripMod,float sheetRim,float flow){
  float base=.026+.075*fresnel+.19*ripSpec+.09*max(0.,ripMod)+.09*sheetRim;
  return base*(1.-smoothstep(.74,1.,abs(across)))*mix(.65,1.,flow);
}
float eaveStreamAlpha(float q,float fresnel,float ripSpec,float ripMod,float coreCA,float flow){
  // Clear water column matching the sheet's glassy translucency: thin bright Fresnel edge
  // glints, faint shimmering axial core highlight, and moving ripple modulation — no white fill.
  float edgeRim=smoothstep(.48,.82,q)*(1.-smoothstep(.82,1.,q));
  float body=.018+.11*fresnel+.20*edgeRim*(.35+.65*fresnel)+.16*ripSpec+.075*max(0.,ripMod)+.065*coreCA;
  return body*(1.-smoothstep(.78,1.,q))*mix(.62,1.,flow);
}
float eaveLodDensity(float d){
  return mix(1.,.35,smoothstep(22.,54.,d))*(1.-smoothstep(95.,120.,d));
}
`;
const vertexShader=waterShape+`
attribute vec4 eaveTop,eaveMeta;attribute float eaveBottom,eaveRank;
uniform float eaveTime,eaveFlow,eaveMist,eaveDensity,eaveViewportHeight;
varying vec2 waterUv;varying vec3 waterWorld;varying vec4 waterInfo,waterState;
void main(){
  waterUv=uv;
  float seed=eaveTop.w,len=eaveTop.y-eaveBottom;
  float eaveS=eaveMeta.x,cellStep=eaveMeta.y,sheetCap=eaveMeta.z;
  bool isPour=sheetCap<-.001;
  float pourShare=isPour?-sheetCap:0.;
  vec3 pourDir=vec3(cos(eaveMeta.w),0.,sin(eaveMeta.w));
  float d=distance(cameraPosition,eaveTop.xyz);
  float lod=eaveMist>.5?1.-smoothstep(8.,25.,d):eaveLodDensity(d);
  float density=lod*eaveDensity;
  if(!isPour&&eaveRank>density){gl_Position=vec4(2.,2.,2.,1.);return;}
  if(isPour&&(eaveFlow<=.002||lod<=.001)){gl_Position=vec4(2.,2.,2.,1.);return;}
  float tauEnd=eaveFallTime(len);
  float sheet=isPour||eaveMist>.5?0.:eaveSheetAmount(eaveS,eaveTime,eaveFlow,sheetCap)*(1.-smoothstep(22.,42.,d));
  float pourAct=smoothstep(.002,.12,eaveFlow)*clamp(.25+.75*pourShare,.2,1.);
  float actTop=isPour?pourAct:eaveActivity(eaveS,eaveTime,seed,eaveFlow);
  float actBot=isPour?pourAct:eaveActivity(eaveS,eaveTime-tauEnd,seed,eaveFlow);
  float liveMax=max(max(actTop,actBot),sheet);
  if(liveMax<.008){gl_Position=vec4(2.,2.,2.,1.);return;}
  // Whole-instance GPU frustum rejection; no per-frame CPU instance visits.
  vec3 lowPos=isPour?vec3(eaveTop.x+pourDir.x*eaveS,eaveBottom,eaveTop.z+pourDir.z*eaveS):vec3(eaveTop.x,eaveBottom,eaveTop.z);
  vec4 topClip=projectionMatrix*viewMatrix*vec4(eaveTop.xyz,1.);
  vec4 lowClip=projectionMatrix*viewMatrix*vec4(lowPos,1.);
  if((topClip.x < -topClip.w&&lowClip.x < -lowClip.w)||(topClip.x > topClip.w&&lowClip.x > lowClip.w)
    ||(topClip.y < -topClip.w&&lowClip.y < -lowClip.w)||(topClip.y > topClip.w&&lowClip.y > lowClip.w)
    ||(topClip.w<0.&&lowClip.w<0.)){gl_Position=vec4(2.,2.,2.,1.);return;}
  vec3 world=eaveTop.xyz;
  vec3 right=vec3(viewMatrix[0][0],0.,viewMatrix[2][0]);right=normalize(right+vec3(.00001,0.,0.));
  float vp=max(abs(projectionMatrix[1][1])*max(eaveViewportHeight,1.),1.);
  float pxFloor=smoothstep(7.,12.,d);
  float cov=1.,eaveU=eaveS,actV=actBot,sheetV=0.,acrossStream=uv.x*2.-1.;
  if(eaveMist>.5){
    float pulse=fract(eaveTime*(2.7+seed*3.)+seed*23.);
    float pScale=isPour?(.7+.5*pourShare):1.;
    float physW=eaveSprayWidth(seed,eaveFlow)*(.6+.4*actBot)*pScale,physH=eaveSprayHeight(seed,eaveFlow)*(.6+.4*actBot)*pScale;
    if(isPour)world.xz+=pourDir.xz*eaveS;
    world.y=eaveBottom+.008;
    world+=right*((pulse-.5)*.035);
    vec4 cEye=viewMatrix*vec4(world,1.);
    float minPx=2.4*pxFloor*(projectionMatrix[3][3]>.5?1.:max(-cEye.z,.001))/vp;
    float drawnW=max(physW,minPx),drawnH=max(physH,minPx);
    cov=(physW/drawnW)*(physH/drawnH)*actBot;
    world.y+=uv.y*drawnH;
    world+=right*((uv.x-.5)*drawnW);
  }else if(isPour){
    float arcBlend=smoothstep(.03,.07,eaveS);
    float fall=mix(uv.y,uv.y*uv.y,arcBlend)*len;
    world.y=eaveTop.y-fall;
    world+=pourDir*(eaveS*uv.y);
    actV=actTop;
    float wobble=eaveWobble(fall,eaveTime,seed)*smoothstep(0.,.15,fall)*(1.-.75*arcBlend);
    vec4 cEye=viewMatrix*vec4(world+right*wobble,1.);
    float minW=2.4*pxFloor*(projectionMatrix[3][3]>.5?1.:max(-cEye.z,.001))/vp;
    float swell=.86+.26*eaveNoise1((eaveTime-eaveFallTime(fall))*11.3+seed*97.3);
    float streamW=cellStep*(.52+.48*eaveFlow)*swell*mix(1.,.82,smoothstep(0.,.75,uv.y));
    float drawnW=max(streamW,minW);
    cov=streamW/drawnW;
    float xOff=(uv.x-.5)*drawnW;
    world+=right*(wobble+xOff);
    eaveU=seed*17.3+xOff;
    acrossStream=uv.x*2.-1.;
    sheetV=-pourShare;
  }else{
    float fall=uv.y*len;
    world.y=eaveTop.y-fall;
    actV=mix(actTop,actBot,uv.y);
    // Keep sheet quad uniformly wide over the curtain zone (0..0.95 m) and only narrow well
    // below the ragged lower edge so no mesh segment ever pinches into triangular icicles.
    float quadSheet=smoothstep(.04,.16,sheet)*(1.-smoothstep(.95,1.35,fall));
    float wobble=eaveWobble(fall,eaveTime,seed)*smoothstep(0.,.15,fall);
    vec4 cEye=viewMatrix*vec4(world+right*(wobble*(1.-quadSheet)),1.);
    float minW=2.4*pxFloor*(projectionMatrix[3][3]>.5?1.:max(-cEye.z,.001))/vp;
    float streamW=eaveWidth(fall,eaveTime,seed,eaveFlow)*(.65+.75*actV);
    float drawnStreamW=max(streamW,minW);
    float sheetW=max(cellStep*1.16,drawnStreamW);
    float drawnW=mix(drawnStreamW,sheetW,quadSheet);
    cov=streamW/drawnStreamW;
    // Align merged sheer-descent quads coplanar with the eave edge; streams billboard.
    vec3 eaveTan=vec3(cos(eaveMeta.w),0.,sin(eaveMeta.w));
    // Facing the camera may flip the tangent; keep the along-eave coordinate in
    // the eave's own direction so neighbouring sheet quads stay continuous.
    float sg=dot(eaveTan,right)<0.?-1.:1.;
    eaveTan*=sg;
    vec3 spanDir=normalize(mix(right,eaveTan,quadSheet));
    float xOff=(uv.x-.5)*drawnW;
    world+=right*(wobble*(1.-quadSheet))+spanDir*xOff;
    eaveU=eaveS+mix(1.,sg,quadSheet)*xOff;
    acrossStream=(xOff-wobble*quadSheet)/(drawnStreamW*.5);
    sheetV=sheet;
  }
  waterWorld=world;
  vec4 eye=viewMatrix*vec4(world,1.);
  waterInfo=vec4(seed,len,-eye.z,cov);
  waterState=vec4(eaveU,sheetV,actV,acrossStream);
  gl_Position=projectionMatrix*eye;
}`;
const fragmentShader=waterShape+`
uniform float eaveTime,eaveFlow,eaveWet,eaveMist,eaveFog;
uniform vec3 eaveColour;
uniform vec4 eaveLamps[4];uniform vec3 eaveLampColours[4];
varying vec2 waterUv;varying vec3 waterWorld;varying vec4 waterInfo,waterState;
// Analytic 2D polynomial ripple gradient (same family as weatherRoofGrad, zero transcendentals).
vec2 eaveFilmGrad(vec2 p){
  vec2 i=floor(p),f=fract(p);
  vec2 du=f*(1.-f);
  vec4 x=fract(i.x*.1031+vec4(0.,.1031,0.,.1031));
  vec4 y=fract(i.y*.1030+vec4(0.,0.,.1030,.1030));
  vec4 q=x*19.3+(y*31.7+11.1);
  vec4 h=fract(q*q);
  return du*vec2(mix(h.y-h.x,h.w-h.z,f.y),mix(h.z-h.x,h.w-h.y,f.x));
}
void main(){
  float seed=waterInfo.x,len=waterInfo.y,depth=waterInfo.z,cov=clamp(waterInfo.w,0.,1.);
  float dist=distance(waterWorld,cameraPosition);
  float nearFade=eaveNearFade(dist,depth);
  if(nearFade<.001)discard;
  if(eaveMist>.5){
    float alpha=eaveSpray(waterUv.x*2.-1.,waterUv.y,eaveTime,seed,eaveFlow)*cov;
    alpha*=nearFade*min(1.,eaveWet*5.)*exp(-eaveFog*dist);
    if(alpha<.001)discard;
    vec3 col=eaveColour*1.05;
    for(int i=0;i<4;i++){
      vec3 delta=waterWorld-eaveLamps[i].xyz;
      col+=eaveLampColours[i]*eaveLamps[i].w/(1.+dot(delta,delta));
    }
    gl_FragColor=vec4(col,alpha);
    #include <tonemapping_fragment>
    #include <colorspace_fragment>
    return;
  }
  bool isPour=waterState.y<-.001;
  float pourShare=isPour?-waterState.y:0.;
  float eaveU=waterState.x,sheetAmt=isPour?0.:waterState.y,act=waterState.z,acrossStream=waterState.w;
  float fall=waterUv.y*len,quadAcross=waterUv.x*2.-1.;
  float tEmit=eaveTime-eaveFallTime(fall);
  // Vertical filament breakup of the sheer sheet: solid near the lip, splitting vertically
  // into bright strands and drops lower down (zero horizontal U-curves or closed loops).
  float sheetFall=0.,sheetRim=0.;
  if(sheetAmt>.02){
    float f1=eaveNoise1(eaveU*18.7+tEmit*.35);
    float f2=eaveNoise1(eaveU*43.1-tEmit*1.15+13.7);
    float fil=f1*.60+f2*.40;
    float dropFrac=smoothstep(.05,.90,fall);
    float sheetBase=smoothstep(.04,.32,sheetAmt);
    float tear=1.-smoothstep(fil*.72,fil*.72+.34,dropFrac);
    sheetFall=sheetBase*tear;
    // Highlight tearing vertical filament tips, never a horizontal outline stroke.
    sheetRim=sheetFall*smoothstep(.18,.80,dropFrac)*smoothstep(.38,.88,fil);
  }
  float live=max(act,sheetFall);
  if(live<.01)discard;
  float locFlow=clamp(eaveFlow*(.55+.65*live),0.,1.);
  float rawPres=eavePresence(fall,len,eaveTime,seed,locFlow);
  float pres=isPour?mix(1.,rawPres,smoothstep(.25,1.2,fall)):mix(rawPres,1.,sheetFall);
  if(pres<.01)discard;
  // Silhouette necking toward breakup gaps on streams; merged curtain uses full quadAcross.
  float narrow=mix(.50,1.,pres);
  float q=abs(acrossStream)/max(narrow,.25);
  if(q>=1.&&sheetFall<.01&&cov>.5)discard;
  if(abs(acrossStream)>=1.&&sheetFall<.01)discard;
  float qClamped=min(q,1.);
  // High-frequency vertical micro-ripple filaments continuing weatherRoofFilm at free-fall speed.
  vec2 rip=eaveFilmGrad(vec2(eaveU*64.,tEmit*16.)+vec2(seed*17.3,seed*41.1)*(1.-sheetFall))*2.2;
  vec3 V=normalize(cameraPosition-waterWorld);
  vec3 fwd=normalize(vec3(V.x,0.,V.z)+vec3(0.,0.,.00001));
  vec3 right=vec3(fwd.z,0.,-fwd.x);
  float cyl=1.-sheetFall;
  vec3 nBase=right*(clamp(acrossStream,-1.,1.)*.92*cyl)+fwd*mix(1.,sqrt(max(.08,1.-qClamped*qClamped)),cyl);
  vec3 N=normalize(nBase+right*(rip.x*mix(.95,1.45,sheetFall))+vec3(0.,rip.y*mix(.75,1.15,sheetFall),0.));
  float ndv=clamp(dot(N,V),0.,1.);
  float f1=1.-ndv,f2=f1*f1,fresnel=.02+.98*f2*f2;
  vec3 R=reflect(-V,N);
  // Upward-tilted ripple facets and internal cylinder refraction redirect overhead sky
  // even when looking downward at an eave (poolhouse_focus, roofclose, overview).
  float skyR=max(R.y,.22+rip.y*.65+abs(rip.x)*.25);
  float skyMix=smoothstep(-.15,.65,skyR);
  float ry=max(0.,skyR),ry2=ry*ry,ry4=ry2*ry2,ry8=ry4*ry4;
  float glint=eaveGlint(fall,eaveTime,seed);
  float ripMag=length(rip);
  float ripMod=clamp((rip.x*.75+rip.y*.65)*1.15,-.35,.35);
  float ripSpec=ry8*(.40+1.25*ripMag)+glint*(.45+.85*fresnel)+smoothstep(.16,.52,ripMag)*(.34*sheetFall+.24*cyl);
  // Clear glassy water column: faint shimmering axial core caustic + thin bright Fresnel edges
  // matching the sheet's translucency up close; gentle lift at mid/overview distance.
  float nearLip=1.-smoothstep(.15,1.35,fall);
  float q2=qClamped*qClamped;
  float coreCA=(1.-smoothstep(0.,.32,q2))*(.30+.30*nearLip+.65*glint+.40*ripMag);
  float midStreamBoost=1.+.65*smoothstep(11.,22.,dist);
  float pourCore=(1.-smoothstep(0.,.22,q2))*(.35+.55*glint+.45*ripSpec);
  float pourGain=isPour?mix(.30,.54,pourShare):1.;
  float streamAlpha=(eaveStreamAlpha(qClamped,fresnel,ripSpec,ripMod,coreCA,eaveFlow)+(isPour?pourCore*.14:0.))*midStreamBoost*pourGain;
  float midSheetBoost=1.+.45*smoothstep(10.,22.,dist)*(1.-smoothstep(26.,42.,dist));
  float sheetAlpha=eaveSheetAlpha(quadAcross,fresnel,ripSpec,ripMod,sheetRim,eaveFlow)*midSheetBoost;
  float resolved=streamAlpha*(1.-sheetFall)*act+sheetAlpha*sheetFall;
  float thin=mix(1.,.35,smoothstep(22.,54.,dist));
  float effCov=min(1.,cov/(thin*.55));
  float farDamp=mix(1.,.46,smoothstep(28.,68.,dist));
  float thread=(.50+.55*ripSpec)*(1.-smoothstep(.18,1.,min(abs(acrossStream),1.)))*mix(.65,1.,eaveFlow)*farDamp;
  float alpha=pres*mix(thread*effCov*smoothstep(0.,.45,act)+sheetAlpha*sheetFall,resolved,cov);
  float endFade=isPour?(1.-smoothstep(.78,1.,waterUv.y)):(1.-smoothstep(.985,1.,waterUv.y));
  alpha*=smoothstep(0.,.035,waterUv.y)*endFade;
  alpha*=1.-smoothstep(95.,120.,dist);
  alpha*=nearFade*min(1.,eaveWet*5.)*exp(-eaveFog*dist);
  if(alpha<.001)discard;
  // Cool neutral silver sky reflection (same desaturation as splash_shapes) so clear water
  // stays bright crisp silver over walls/windows without beige tint or dark smudging.
  float luma=dot(eaveColour,vec3(.2126,.7152,.0722));
  vec3 skyRad=mix(vec3(luma),eaveColour,.25);
  float streamGain=max(1.02,1.08+.38*skyMix+1.05*ripSpec+.38*ripMod+.45*coreCA)*(isPour?(.90+.18*pourCore):1.);
  float sheetGain=eaveSheetLumGain(ripMod,skyMix,ripSpec,sheetRim);
  vec3 waterCol=skyRad*mix(streamGain,sheetGain,sheetFall);
  for(int i=0;i<4;i++){
    vec3 toLamp=eaveLamps[i].xyz-waterWorld;
    float d2=dot(toLamp,toLamp);
    float dl=max(0.,dot(R,toLamp))*inversesqrt(max(d2,.0001));
    float l2=dl*dl,l4=l2*l2,l8=l4*l4,ls=l8*l8;
    waterCol+=eaveLampColours[i]*eaveLamps[i].w*(.35+2.6*ls)/(1.+d2);
  }
  gl_FragColor=vec4(waterCol,alpha);
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
}`;

function geometry(instances,segments) {
  const g=new THREE.InstancedBufferGeometry(),vertices=[],uv=[],indices=[];
  for(let j=0;j<=segments;j++)for(let i=0;i<2;i++){vertices.push(i-.5,j/segments,0);uv.push(i,j/segments);}
  for(let j=0;j<segments;j++){const k=j*2;indices.push(k,k+1,k+3,k,k+3,k+2);}
  g.setAttribute('position',new THREE.Float32BufferAttribute(vertices,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2));g.setIndex(indices);
  const streamCount=instances.reduce((n,i)=>n+(i.pour?0:1),0);
  let streamIdx=0;
  g.setAttribute('eaveTop',new THREE.InstancedBufferAttribute(new Float32Array(instances.flatMap(i=>[...i.top,i.seed])),4));
  g.setAttribute('eaveMeta',new THREE.InstancedBufferAttribute(new Float32Array(instances.flatMap(i=>[i.eaveS,i.cellStep,i.sheetCap,i.angle])),4));
  g.setAttribute('eaveBottom',new THREE.InstancedBufferAttribute(new Float32Array(instances.map(i=>i.bottom)),1));
  g.setAttribute('eaveRank',new THREE.InstancedBufferAttribute(new Float32Array(instances.map(i=>i.pour?0:(streamIdx+++.5)/Math.max(1,streamCount))),1));
  const box=new THREE.Box3();
  for(const i of instances){
    box.expandByPoint(new THREE.Vector3(...i.top));
    box.expandByPoint(new THREE.Vector3(i.top[0]+(i.pourDir?.[0]||0)*(i.pourForward||0),i.bottom,i.top[2]+(i.pourDir?.[2]||0)*(i.pourForward||0)));
  }
  if(instances.length){box.expandByScalar(.5);g.boundingBox=box;g.boundingSphere=box.getBoundingSphere(new THREE.Sphere());}
  g.instanceCount=instances.length;return g;
}

export function createEaveStreams(scene,{tier='high',colour=null}={}) {
  const group=new THREE.Group();group.name='weather-eave-streams';group.visible=false;scene.add(group);
  const uniforms={eaveTime:{value:0},eaveFlow:{value:0},eaveWet:{value:0},eaveFog:{value:0},eaveDensity:{value:0},
    eaveViewportHeight:{value:720},
    eaveColour:colour||{value:new THREE.Vector3(.6,.7,.8)},
    eaveLamps:{value:Array.from({length:4},()=>new THREE.Vector4())},
    eaveLampColours:{value:Array.from({length:4},()=>new THREE.Color())}};
  const materials=[0,1].map(kind=>new THREE.ShaderMaterial({name:'EaveWater',vertexShader,fragmentShader,
    uniforms:{...uniforms,eaveMist:{value:kind}},transparent:true,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true}));
  let data={eaves:[],instances:[],pours:[]},streams=null,mist=null,disposed=false,maximum=0,poursCount=0,selectedStreams=0;
  let lastFlow=null,lastTime=null,decliningAt=null,lastDecline=-Infinity;
  const clear=()=>{for(const o of [streams,mist])if(o){o.geometry.dispose();group.remove(o);}streams=mist=null;maximum=poursCount=selectedStreams=0;group.visible=false;};
  return {group,uniforms,get data(){return data;},get streams(){return streams;},get mist(){return mist;},
    setPlan(plan={},roofs=new Map(),kit={},gutters=null){
      if(disposed)return;clear();data=eaveInstances(plan||{},roofs,kit,gutters);
      poursCount=data.pours?.length||0;
      const streamTotal=data.instances.length-poursCount;
      selectedStreams=Math.floor(streamTotal*(tier==='low'?.35:tier==='medium'?.65:1));
      const count=poursCount+selectedStreams;
      maximum=count;
      if(!count)return;
      const selected=data.instances.slice(0,count);
      streams=new THREE.Mesh(geometry(selected,12),materials[0]);mist=new THREE.Mesh(geometry(selected,1),materials[1]);
      streams.name='eave-streams';mist.name='eave-mist';
      group.add(streams,mist);
    },
    update({flow=0,wet=0}={},seconds=0,{camera=null,target=null,level='house',unlit=false,neutral=false,fog=0,light=null,lamps=[],viewportHeight=null}={}){
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
      if(Number.isFinite(viewportHeight)&&viewportHeight>0)uniforms.eaveViewportHeight.value=viewportHeight;
      const steep=camera&&target&&(camera.position.y-target.y)/Math.max(.001,camera.position.distanceTo(target))>.94;
      const dist=camera&&streams?streams.geometry.boundingBox.distanceToPoint(camera.position):0;
      const density=camera&&streams?lodDensity(dist):1;
      const mistDensity=camera&&streams?1-smooth(8,MIST_FAR,dist):1;
      if(streams){
        streams.geometry.instanceCount=flow>.002&&wet>0&&density>0?poursCount+Math.ceil(selectedStreams*density*demand):0;
        mist.geometry.instanceCount=flow>.26&&wet>0&&mistDensity>0?Math.min(maximum,poursCount+Math.ceil(selectedStreams*mistDensity*demand*.5)):0;
        mist.visible=mist.geometry.instanceCount>0;
      }
      group.visible=!!streams&&density>0&&!unlit&&!neutral&&(level==='house'||level==='building')&&!steep&&flow>.002&&wet>0;
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
