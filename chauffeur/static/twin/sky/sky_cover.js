import * as THREE from 'three';
import { buildingBase, buildingFootprint, inPolygon, edgeDistance } from '../twin_ground.js';
import { roofMeshGroups } from '../twin_roof.js';

const FT=.3048, EDGE=.6, EPS=.002;
export const HEIGHT_NONE=-1e4;
const owners=new WeakMap();
const written=new WeakMap();
const unclipped=new WeakMap();
// Generated roof snapshots are immutable; slab refresh replaces its array.
// Identity keys avoid serializing every roof vertex on each editor drag frame.
const references=new WeakMap();let nextReference=0;
const reference=value=>{if(!references.has(value))references.set(value,++nextReference);return references.get(value);};

// All samples are world metres. Roof triangles come from the generated draw
// geometry (including awnings, shed extensions and overhangs), before batching.
// The section mesh is also available to independent yard/precipitation callers.
export function createSkyCover(plan={},roofs=new Map()) {
  roofs=roofs||new Map();
  const buildings=[],triangles=[],slabs=[];
  const staticParts=[],dynamicParts=[];
  let minimumRoof=Infinity;
  const bounds={x0:Infinity,x1:-Infinity,z0:Infinity,z1:-Infinity,top:-Infinity};
  const include=([x,y,z])=>{bounds.x0=Math.min(bounds.x0,x);bounds.x1=Math.max(bounds.x1,x);bounds.z0=Math.min(bounds.z0,z);bounds.z1=Math.max(bounds.z1,z);bounds.top=Math.max(bounds.top,y);};
  for(const b of plan.buildings||[]) {
    const angle=(b.rotation||0)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),pos=b.position||[0,0],base=buildingBase(plan,b);
    const point=(x,y,h)=>[(pos[0]+x*c-y*s)*FT,(base+h)*FT,-(pos[1]+x*s+y*c)*FT];
    const local=(x,z)=>{const dx=x/FT-pos[0],dy=-z/FT-pos[1];return [dx*c+dy*s,-dx*s+dy*c];};
    const levels=b.levels||[],top=Math.max(0,...levels.map(l=>l.elevation+l.ceiling))*FT+base*FT;
    const footprint=buildingFootprint(b),corners=footprint.map(p=>point(...p,top/FT-base));
    buildings.push({local,footprint,top,x0:Math.min(...corners.map(p=>p[0])),x1:Math.max(...corners.map(p=>p[0])),
      z0:Math.min(...corners.map(p=>p[2])),z1:Math.max(...corners.map(p=>p[2])),
      porches:(b.rooms||[]).filter(r=>r.kind==='porch').map(r=>r.polygon)});
    corners.forEach(include);
    const surfaces=roofs.get(b.id),roofPositions=surfaces?.coverPositions||roofMeshGroups(b.roof?.sections||[]).positions;
    staticParts.push([b.id,pos,angle,base,footprint,top,buildings.at(-1).porches,reference(roofPositions)]);
    dynamicParts.push(surfaces?.slabPositions?reference(surfaces.slabPositions):[levels,(b.rooms||[]).map(r=>[r.level,r.kind,r.state,r.polygon,r.floor_offset_ft])]);
    for(const [positions,roof] of [[roofPositions,true],[surfaces?.slabPositions||[],false]])for(let i=0;i<positions.length;i+=9) {
      const p=[0,3,6].map(j=>point(positions[i+j],positions[i+j+1],positions[i+j+2]));
      p.forEach(include);
      if(roof)for(const v of p)minimumRoof=Math.min(minimumRoof,v[1]);
      const den=(p[1][2]-p[2][2])*(p[0][0]-p[2][0])+(p[2][0]-p[1][0])*(p[0][2]-p[2][2]);
      if(Math.abs(den)<1e-10)continue;
      triangles.push({p,den,roof,x0:Math.min(...p.map(v=>v[0])),x1:Math.max(...p.map(v=>v[0])),
        z0:Math.min(...p.map(v=>v[2])),z1:Math.max(...p.map(v=>v[2]))});
    }
    // Upper slabs and ceilings remain cover when the editor peels a roof away.
    // Keep the plan's concave outlines and room offsets, rather than a box.
    for(const l of surfaces?.slabPositions ? [] : levels) {
      for(const p of l.outline||[])include(point(...p,l.elevation));
      if(l.outline?.length>=3&&l.elevation>Math.min(...levels.map(level=>level.elevation)))slabs.push({local,polygon:l.outline,height:(base+l.elevation)*FT});
      for(const r of b.rooms||[])if(r.level===l.id&&r.kind!=='porch'&&r.state!=='ghost'&&r.polygon?.length>=3&&l.elevation>Math.min(...levels.map(level=>level.elevation)))
        slabs.push({local,polygon:r.polygon,height:(base+l.elevation+(r.floor_offset_ft||0))*FT});
    }
  }
  const grid=new Map(),cell=4;
  for(const t of triangles)for(let x=Math.floor((t.x0-EDGE)/cell);x<=Math.floor((t.x1+EDGE)/cell);x++)
    for(let z=Math.floor((t.z0-EDGE)/cell);z<=Math.floor((t.z1+EDGE)/cell);z++){
      const key=x+':'+z;if(!grid.has(key))grid.set(key,[]);grid.get(key).push(t);
    }
  const nearby=(x,z)=>grid.get(Math.floor(x/cell)+':'+Math.floor(z/cell))||[];
  function height(t,x,z) {
    if(x<t.x0-1e-6||x>t.x1+1e-6||z<t.z0-1e-6||z>t.z1+1e-6)return null;
    const [a,b,c]=t.p,u=((b[2]-c[2])*(x-c[0])+(c[0]-b[0])*(z-c[2]))/t.den;
    const v=((c[2]-a[2])*(x-c[0])+(a[0]-c[0])*(z-c[2]))/t.den,w=1-u-v;
    return Math.min(u,v,w)>=-1e-6?u*a[1]+v*b[1]+w*c[1]:null;
  }
  const roofHeight=(x,_y,z)=>{
    let top=-Infinity;
    for(const t of nearby(x,z)){if(!t.roof)continue;const h=height(t,x,z);if(h!==null)top=Math.max(top,h);}
    return top;
  };
  const interior=(x,y,z)=>buildings.some(b=>{
    if(x<b.x0-1e-6||x>b.x1+1e-6||z<b.z0-1e-6||z>b.z1+1e-6)return false;
    const p=b.local(x,z);
    if(!inPolygon(b.footprint,...p)||b.porches.some(poly=>inPolygon(poly,...p)))return false;
    // Below every roof (or the fallback indoor top), the exact roof ray test
    // cannot change the answer. This is most floor, furniture and wall data.
    if(y<Math.min(b.top,minimumRoof)-EPS)return true;
    const roof=roofHeight(x,y,z),top=Number.isFinite(roof)?roof:b.top;
    return y<top-EPS;
  });
  function open(x,y,z,roofFace=false,withSlabs=true) {
    if(!Number.isFinite(x)||!Number.isFinite(y)||!Number.isFinite(z))return 0;
    if(roofFace)return 1;
    if(y>=bounds.top-EPS||x<bounds.x0-EDGE||x>bounds.x1+EDGE||z<bounds.z0-EDGE||z>bounds.z1+EDGE)return 1;
    if(interior(x,y,z))return 0;
    if(withSlabs)for(const slab of slabs)if(y<slab.height-EPS&&inPolygon(slab.polygon,...slab.local(x,z)))return 0;
    let distance=EDGE;
    for(const t of nearby(x,z)) {
      if(!withSlabs&&!t.roof)continue;
      if(x<t.x0-EDGE||x>t.x1+EDGE||z<t.z0-EDGE||z>t.z1+EDGE)continue;
      const h=height(t,x,z);
      if(h!==null&&y<h-EPS)return 0;
      if(h!==null||!t.roof)continue; // A roof never covers its own upward face.
      for(let i=0;i<3;i++){
        const a=t.p[i],b=t.p[(i+1)%3];
        if(y>=Math.max(a[1],b[1])-EPS)continue;
        distance=Math.min(distance,edgeDistance([x,z],[a[0],a[2]],[b[0],b[2]]));
      }
    }
    // The ramp is OUTSIDE the eave: everything physically covered stays dry.
    return Math.max(0,Math.min(1,distance/EDGE));
  }
  function slabOpen(x,y,z) {
    for(const slab of slabs)if(y<slab.height-EPS&&inPolygon(slab.polygon,...slab.local(x,z)))return 0;
    for(const t of nearby(x,z))if(!t.roof){const h=height(t,x,z);if(h!==null&&y<h-EPS)return 0;}
    return 1;
  }
  for(const slab of slabs){const xs=slab.polygon.map(p=>p[0]),ys=slab.polygon.map(p=>p[1]);slab.box=[Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];}
  // Every cover rule is "covered below some height here", so blocked(x,y,z) is
  // exactly y < coverTop(x,z)-EPS (apart from a point lying exactly on an eave
  // line). -Infinity: open sky at every height.
  function coverTop(x,z) {
    if(!Number.isFinite(x)||!Number.isFinite(z)||x<bounds.x0-EDGE||x>bounds.x1+EDGE||z<bounds.z0-EDGE||z>bounds.z1+EDGE)return -Infinity;
    let top=-Infinity;
    for(const b of buildings){
      if(x<b.x0-1e-6||x>b.x1+1e-6||z<b.z0-1e-6||z>b.z1+1e-6)continue;
      const p=b.local(x,z);
      if(!inPolygon(b.footprint,...p)||b.porches.some(poly=>inPolygon(poly,...p)))continue;
      const roof=roofHeight(x,0,z);
      top=Math.max(top,Math.min(b.top,minimumRoof),Number.isFinite(roof)?roof:b.top);
    }
    for(const slab of slabs){
      if(slab.height<=top)continue;
      const [u,v]=slab.local(x,z);
      if(u>=slab.box[0]&&v>=slab.box[1]&&u<=slab.box[2]&&v<=slab.box[3]&&inPolygon(slab.polygon,u,v))top=slab.height;
    }
    for(const t of nearby(x,z)){const h=height(t,x,z);if(h!==null&&h>top)top=h;}
    return Math.min(top,bounds.top);
  }
  // Baked once per cover for GPU lookups (falling rain). Texel centres sample
  // coverTop; NONE marks open sky. Bounds are [x0,z0,x1,z1] in world metres.
  let field=null;
  function heightField(cell=.3) {
    if(field&&field.cell===cell)return field;
    if(!Number.isFinite(bounds.x0)){field={cell,width:1,height:1,bounds:[0,0,1,1],data:new Float32Array([HEIGHT_NONE])};return field;}
    const x0=bounds.x0-EDGE,z0=bounds.z0-EDGE,width=Math.max(1,Math.ceil((bounds.x1+EDGE-x0)/cell)),height=Math.max(1,Math.ceil((bounds.z1+EDGE-z0)/cell));
    const data=new Float32Array(width*height);
    for(let j=0;j<height;j++)for(let i=0;i<width;i++){
      const top=coverTop(x0+(i+.5)*cell,z0+(j+.5)*cell);
      data[j*width+i]=Number.isFinite(top)?top-EPS:HEIGHT_NONE;
    }
    field={cell,width,height,bounds:[x0,z0,x0+width*cell,z0+height*cell],data};
    return field;
  }
  // Exact projected outer drip-line segments in world XZ (metres). Built lazily
  // on first SDF or horizontal-face clip query. Shared interior triangle edges
  // (covered on both sides) are dropped before intersection splitting, and
  // collinear sub-segments along a single eave are merged.
  let edgeCache=null;
  function buildCoverEdges() {
    if(edgeCache)return edgeCache;
    const r=v=>Math.round(v*1e3);
    const ptKey=(x,z)=>`${r(x)},${r(z)}`;
    const raw=[],seen=new Set();
    const offer=(ax,az,bx,bz,h)=>{
      const len=Math.hypot(bx-ax,bz-az);
      if(len<1e-4)return;
      const k1=`${ptKey(ax,az)}|${ptKey(bx,bz)}`,k2=`${ptKey(bx,bz)}|${ptKey(ax,az)}`;
      const key=k1<k2?k1:k2;
      if(seen.has(key))return;seen.add(key);
      raw.push({ax,az,bx,bz,h,x0:Math.min(ax,bx),x1:Math.max(ax,bx),z0:Math.min(az,bz),z1:Math.max(az,bz)});
    };
    // Oriented-edge cancellation per layer (roof vs slab): an edge shared by two
    // consistently oriented triangles in opposite directions has cover on both
    // sides and can never lie on an outer drip line.
    for(const isRoof of [true,false]){
      const directed=new Map();
      for(const t of triangles){
        if(t.roof!==isRoof)continue;
        let [a,b,c]=t.p;
        if((b[0]-a[0])*(c[2]-a[2])-(b[2]-a[2])*(c[0]-a[0])<0){const tmp=b;b=c;c=tmp;}
        for(const [u,v] of [[a,b],[b,c],[c,a]]){
          const dk=`${ptKey(u[0],u[2])}>${ptKey(v[0],v[2])}`;
          const prev=directed.get(dk);
          const h=Math.max(u[1],v[1]);
          if(!prev||h>prev.h)directed.set(dk,{ax:u[0],az:u[2],bx:v[0],bz:v[2],h,rk:`${ptKey(v[0],v[2])}>${ptKey(u[0],u[2])}`});
        }
      }
      for(const e of directed.values())if(!directed.has(e.rk))offer(e.ax,e.az,e.bx,e.bz,e.h);
    }
    for(const b of plan.buildings||[]){
      const angle=(b.rotation||0)*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle),pos=b.position||[0,0],base=buildingBase(plan,b);
      const levels=b.levels||[],top=(base+Math.max(0,...levels.map(l=>l.elevation+l.ceiling)))*FT;
      const toW=([x,y])=>[(pos[0]+x*c-y*s)*FT,-(pos[1]+x*s+y*c)*FT];
      const fp=buildingFootprint(b).map(toW);
      for(let i=0;i<fp.length;i++){const a=fp[i],d=fp[(i+1)%fp.length];offer(a[0],a[1],d[0],d[1],top);}
    }
    for(const slab of slabs){
      const o=slab.local(0,0),ux=slab.local(1,0),uz=slab.local(0,1);
      const m00=ux[0]-o[0],m10=ux[1]-o[1],m01=uz[0]-o[0],m11=uz[1]-o[1],det=m00*m11-m01*m10;
      if(Math.abs(det)<1e-12)continue;
      const toW=([u,v])=>[((u-o[0])*m11-(v-o[1])*m01)/det,((v-o[1])*m00-(u-o[0])*m10)/det];
      const poly=slab.polygon.map(toW);
      for(let i=0;i<poly.length;i++){const a=poly[i],d=poly[(i+1)%poly.length];offer(a[0],a[1],d[0],d[1],slab.height);}
    }
    // Split overlapping perimeter segments at mutual XZ intersections and keep
    // only true outer drip-line pieces (covered on one side, open sky on the other).
    const pieces=[],outer=[],outerGrid=new Map(),edgeCell=2;
    const put=(map,e)=>{
      for(let gx=Math.floor((e.x0-1)/edgeCell);gx<=Math.floor((e.x1+1)/edgeCell);gx++)
        for(let gz=Math.floor((e.z0-1)/edgeCell);gz<=Math.floor((e.z1+1)/edgeCell);gz++){
          const k=gx+':'+gz;if(!map.has(k))map.set(k,[]);map.get(k).push(e);
        }
    };
    const delta=.012;
    for(let i=0;i<raw.length;i++){
      const e=raw[i],dx=e.bx-e.ax,dz=e.bz-e.az,cuts=[0,1];
      for(let j=0;j<raw.length;j++){
        if(i===j)continue;
        const o=raw[j];
        if(o.x1<e.x0-1e-4||o.x0>e.x1+1e-4||o.z1<e.z0-1e-4||o.z0>e.z1+1e-4)continue;
        const ox=o.bx-o.ax,oz=o.bz-o.az,den=dx*oz-dz*ox;
        if(Math.abs(den)<1e-10){
          const len2=dx*dx+dz*dz;
          for(const [px,pz] of [[o.ax,o.az],[o.bx,o.bz]]){
            if(Math.abs((px-e.ax)*dz-(pz-e.az)*dx)<1e-3*Math.sqrt(len2)){
              const t=((px-e.ax)*dx+(pz-e.az)*dz)/len2;
              if(t>1e-4&&t<1-1e-4)cuts.push(t);
            }
          }
          continue;
        }
        const t=((o.ax-e.ax)*oz-(o.az-e.az)*ox)/den;
        const u=((o.ax-e.ax)*dz-(o.az-e.az)*dx)/den;
        if(t>1e-4&&t<1-1e-4&&u>=-1e-4&&u<=1+1e-4)cuts.push(t);
      }
      cuts.sort((a,b)=>a-b);
      for(let k=0;k+1<cuts.length;k++){
        const t0=cuts[k],t1=cuts[k+1];
        if(t1-t0<1e-4)continue;
        let ax=e.ax+dx*t0,az=e.az+dz*t0,bx=e.ax+dx*t1,bz=e.az+dz*t1;
        const len=Math.hypot(bx-ax,bz-az);
        if(len<1e-3)continue;
        let tx=(bx-ax)/len,tz=(bz-az)/len,nx=-tz,nz=tx;
        const mx=(ax+bx)*.5,mz=(az+bz)*.5;
        const topP=coverTop(mx+nx*delta,mz+nz*delta),topN=coverTop(mx-nx*delta,mz-nz*delta);
        const finP=Number.isFinite(topP),finN=Number.isFinite(topN);
        if(finP===finN)continue;
        let highY;
        if(finP){nx=-nx;nz=-nz;highY=topP;const ta=ax,tb=az;ax=bx;az=bz;bx=ta;bz=tb;tx=-tx;tz=-tz;}
        else highY=topN;
        pieces.push({a:[ax,az],b:[bx,bz],tx,tz,nx,nz,len,highY,lowY:-Infinity,outer:true});
      }
    }
    // Merge adjacent collinear outer pieces along the same drip line.
    const used=new Uint8Array(pieces.length);
    for(let i=0;i<pieces.length;i++){
      if(used[i])continue;
      used[i]=1;
      let ax=pieces[i].a[0],az=pieces[i].a[1],bx=pieces[i].b[0],bz=pieces[i].b[1];
      const {tx,tz,nx,nz}=pieces[i];let highY=pieces[i].highY;
      let merged=true;
      while(merged){
        merged=false;
        for(let j=0;j<pieces.length;j++){
          if(used[j])continue;
          const q=pieces[j];
          if(tx*q.tx+tz*q.tz<.9999||nx*q.nx+nz*q.nz<.9999||Math.abs(highY-q.highY)>.1)continue;
          if(Math.hypot(bx-q.a[0],bz-q.a[1])<5e-3){bx=q.b[0];bz=q.b[1];highY=Math.max(highY,q.highY);used[j]=1;merged=true;}
          else if(Math.hypot(ax-q.b[0],az-q.b[1])<5e-3){ax=q.a[0];az=q.a[1];highY=Math.max(highY,q.highY);used[j]=1;merged=true;}
        }
      }
      const len=Math.hypot(bx-ax,bz-az);
      const seg={a:[ax,az],b:[bx,bz],tx,tz,nx,nz,len,highY,lowY:-Infinity,outer:true,
        x0:Math.min(ax,bx),x1:Math.max(ax,bx),z0:Math.min(az,bz),z1:Math.max(az,bz)};
      outer.push(seg);put(outerGrid,seg);
    }
    edgeCache={outer,outerGrid,edgeCell};
    return edgeCache;
  }
  function coverSignedDistance(x,z) {
    if(!Number.isFinite(x)||!Number.isFinite(z)||!Number.isFinite(bounds.x0)||
      x<bounds.x0-1||x>bounds.x1+1||z<bounds.z0-1||z>bounds.z1+1)return {distance:1,top:HEIGHT_NONE};
    const {outerGrid,edgeCell}=buildCoverEdges();
    const top=coverTop(x,z),covered=Number.isFinite(top);
    const list=outerGrid.get(Math.floor(x/edgeCell)+':'+Math.floor(z/edgeCell))||[];
    let best=1,bestTop=HEIGHT_NONE;
    for(const e of list){
      if(x<e.x0-best||x>e.x1+best||z<e.z0-best||z>e.z1+best)continue;
      const d=edgeDistance([x,z],e.a,e.b);
      if(d<best){best=d;bestTop=e.highY;}
    }
    return {distance:covered?-best:best,top:covered?top-EPS:(best<.9&&Number.isFinite(bestTop)?bestTop-EPS:HEIGHT_NONE)};
  }
  const staticKey=JSON.stringify(staticParts),key=staticKey+'|'+JSON.stringify(dynamicParts);
  return {key,staticKey,bounds,open,slabOpen,staticOpen:(x,y,z,roofFace)=>open(x,y,z,roofFace,false),interior,roofHeight,coverTop,heightField,coverSignedDistance,clipEdges:buildCoverEdges,blocked:(x,y,z)=>open(x,y,z)===0};
}

// Split a convex vertex polygon by a world-XZ line: (p.x - ax)*nx + (p.z - az)*nz = offset.
// Each vertex is a flat array holding [wx, wy, wz, ...interpolatedAttributes].
function splitByLine(poly,ax,az,nx,nz,offset) {
  const pos=[],neg=[];
  const dist=v=>(v[0]-ax)*nx+(v[2]-az)*nz-offset;
  let hasPos=false,hasNeg=false;
  for(const v of poly){const d=dist(v);if(d>1e-3)hasPos=true;else if(d<-1e-3)hasNeg=true;}
  if(!hasPos||!hasNeg)return [poly];
  for(let i=0;i<poly.length;i++){
    const p=poly[i],q=poly[(i+1)%poly.length],dp=dist(p),dq=dist(q);
    if(dp>=-1e-5)pos.push(p);
    if(dp<=1e-5)neg.push(p);
    if(dp>1e-5&&dq<-1e-5||dp<-1e-5&&dq>1e-5){
      const t=dp/(dp-dq),m=new Array(p.length);
      for(let k=0;k<p.length;k++)m[k]=p[k]+t*(q[k]-p[k]);
      pos.push(m);neg.push(m);
    }
  }
  const out=[];
  if(pos.length>=3&&polyXzArea(pos)>=1e-6)out.push(pos);
  if(neg.length>=3&&polyXzArea(neg)>=1e-6)out.push(neg);
  return out.length?out:[poly];
}

function polyXzArea(poly) {
  let a=0;
  for(let i=0;i<poly.length;i++){const p=poly[i],q=poly[(i+1)%poly.length];a+=p[0]*q[2]-q[0]*p[2];}
  return Math.abs(a)*.5;
}

// Clip horizontal upward triangles that straddle an active projected cover edge
// so per-vertex weatherOpen follows the real drip line instead of diagonal grid
// edges or long slab triangles. Preserves indexing on indexed ground meshes so
// only triangles crossing an eave allocate new vertices. Returns null when no
// triangle crosses a boundary.
function clipHorizontalToCover(g,o,effective,cover) {
  if(!cover.clipEdges||!cover.bounds||!Number.isFinite(cover.bounds.x0))return null;
  if(o.userData.clipWeatherOpen===false)return null;
  const skipKinds=new Set(['roof','wall','room','floor','ceiling','trim','opening','fixture','furniture','planting']);
  if(o.userData.kind&&skipKinds.has(o.userData.kind))return null;
  const mats=o.material?(Array.isArray(o.material)?o.material:[o.material]):[];
  if(mats.some(m=>m?.userData?.plantWind))return null;
  let yardPart=null;
  for(let p=o;p;p=p.parent)if(p.userData?.yardPart){yardPart=p.userData.yardPart;break;}
  if(yardPart&&yardPart!=='hardscape'&&yardPart!=='terrain')return null;
  if(!g.boundingBox)g.computeBoundingBox();
  const b=g.boundingBox.clone().applyMatrix4(effective),cb=cover.bounds;
  if(b.max.x<cb.x0-EDGE||b.min.x>cb.x1+EDGE||b.max.z<cb.z0-EDGE||b.min.z>cb.z1+EDGE||b.min.y>=cb.top-EPS)return null;
  const {outer,outerGrid,edgeCell}=cover.clipEdges();
  if(!outer.length)return null;
  const posAttr=g.attributes.position,index=g.index,triCount=(index?index.count:posAttr.count)/3;
  if(!triCount)return null;
  const ranges=(o.userData.snapRanges||g.userData.snapRanges||null);
  const sortedRanges=ranges?[...ranges].sort((a,b)=>a.start-b.start):null;
  const rangeAllowed=r=>!r||yardPart==='hardscape'||yardPart==='terrain'||r.kind==='porch'||r.kind==='deck';
  if(sortedRanges&&!sortedRanges.some(rangeAllowed))return null;
  const p0=new THREE.Vector3(),p1=new THREE.Vector3(),p2=new THREE.Vector3();
  // Pre-transform unique vertices once (avoids 6x redundant Matrix4 multiplies on
  // indexed ground grids) and skip triangles outside cover bounds immediately.
  const vCount=posAttr.count,wx=new Float32Array(vCount),wy=new Float32Array(vCount),wz=new Float32Array(vCount);
  const em=effective.elements;
  const m0=em[0],m1=em[1],m2=em[2],m4=em[4],m5=em[5],m6=em[6],m8=em[8],m9=em[9],m10=em[10],m12=em[12],m13=em[13],m14=em[14];
  for(let i=0;i<vCount;i++){
    const lx=posAttr.getX(i),ly=posAttr.getY(i),lz=posAttr.getZ(i);
    wx[i]=m0*lx+m4*ly+m8*lz+m12;wy[i]=m1*lx+m5*ly+m9*lz+m13;wz[i]=m2*lx+m6*ly+m10*lz+m14;
  }
  const cbX0=cb.x0-EDGE,cbX1=cb.x1+EDGE,cbZ0=cb.z0-EDGE,cbZ1=cb.z1+EDGE,cbTop=cb.top-EPS;
  const candidatesFor=(x0,x1,z0,z1,y)=>{
    const gx0=Math.floor((x0-EDGE)/edgeCell),gx1=Math.floor((x1+EDGE)/edgeCell);
    const gz0=Math.floor((z0-EDGE)/edgeCell),gz1=Math.floor((z1+EDGE)/edgeCell);
    const found=new Set();
    for(let gx=gx0;gx<=gx1;gx++)for(let gz=gz0;gz<=gz1;gz++){
      const list=outerGrid.get(gx+':'+gz);if(!list)continue;
      for(const e of list){
        if(y>=e.highY-EPS||y<e.lowY-EPS)continue;
        if(e.x1+EDGE<x0||e.x0-EDGE>x1||e.z1+EDGE<z0||e.z0-EDGE>z1)continue;
        found.add(e);
      }
    }
    return found;
  };
  const triCrosses=(x0,z0,x1,z1,x2,z2,e,offset)=>{
    const ax=e.a[0],az=e.a[1],nx=e.nx,nz=e.nz,tx=e.tx,tz=e.tz;
    const s0=(x0-ax)*nx+(z0-az)*nz-offset,s1=(x1-ax)*nx+(z1-az)*nz-offset,s2=(x2-ax)*nx+(z2-az)*nz-offset;
    const minS=s0<s1?(s0<s2?s0:s2):(s1<s2?s1:s2),maxS=s0>s1?(s0>s2?s0:s2):(s1>s2?s1:s2);
    if(!(minS<-1e-3&&maxS>1e-3))return false;
    const u0=(x0-ax)*tx+(z0-az)*tz,u1=(x1-ax)*tx+(z1-az)*tz,u2=(x2-ax)*tx+(z2-az)*tz;
    const minU=u0<u1?(u0<u2?u0:u2):(u1<u2?u1:u2),maxU=u0>u1?(u0>u2?u0:u2):(u1>u2?u1:u2);
    const pad=offset>0?EDGE:1e-3;
    return maxU>=-pad&&minU<=e.len+pad;
  };
  const edgeCrosses=(vs,e,offset)=>{
    let minS=Infinity,maxS=-Infinity,minU=Infinity,maxU=-Infinity;
    for(const v of vs){
      const s=(v[0]-e.a[0])*e.nx+(v[2]-e.a[1])*e.nz-offset;
      const u=(v[0]-e.a[0])*e.tx+(v[2]-e.a[1])*e.tz;
      if(s<minS)minS=s;if(s>maxS)maxS=s;
      if(u<minU)minU=u;if(u>maxU)maxU=u;
    }
    const pad=offset>0?EDGE:1e-3;
    return minS<-1e-3&&maxS>1e-3&&maxU>=-pad&&minU<=e.len+pad;
  };
  // Pass 1: find exactly which triangles cross an outer drip line (zero allocations).
  const splitMask=new Uint8Array(triCount);
  let splitCount=0,ri=0;
  for(let f=0;f<triCount;f++){
    if(sortedRanges){
      while(ri<sortedRanges.length&&f*3>=sortedRanges[ri].start+sortedRanges[ri].count)ri++;
      const r=ri<sortedRanges.length&&f*3>=sortedRanges[ri].start?sortedRanges[ri]:null;
      if(!rangeAllowed(r))continue;
    }
    const i0=index?index.getX(f*3):f*3,i1=index?index.getX(f*3+1):f*3+1,i2=index?index.getX(f*3+2):f*3+2;
    const ax=wx[i0],bx=wx[i1],cx=wx[i2];
    const x0=ax<bx?(ax<cx?ax:cx):(bx<cx?bx:cx),x1=ax>bx?(ax>cx?ax:cx):(bx>cx?bx:cx);
    if(x1<cbX0||x0>cbX1)continue;
    const az=wz[i0],bz=wz[i1],cz=wz[i2];
    const z0=az<bz?(az<cz?az:cz):(bz<cz?bz:cz),z1=az>bz?(az>cz?az:cz):(bz>cz?bz:cz);
    if(z1<cbZ0||z0>cbZ1)continue;
    const ay=wy[i0],by=wy[i1],cy=wy[i2],y=(ay+by+cy)/3;
    if(y>=cbTop)continue;
    const e1x=bx-ax,e1y=by-ay,e1z=bz-az,e2x=cx-ax,e2y=cy-ay,e2z=cz-az;
    const fnx=e1y*e2z-e1z*e2y,fny=e1z*e2x-e1x*e2z,fnz=e1x*e2y-e1y*e2x;
    const len=Math.hypot(fnx,fny,fnz);if(len<1e-10||fny/len<=.55)continue;
    const coarse=Math.max(x1-x0,z1-z0)>.45;
    const gx0=Math.floor((x0-EDGE)/edgeCell),gx1=Math.floor((x1+EDGE)/edgeCell);
    const gz0=Math.floor((z0-EDGE)/edgeCell),gz1=Math.floor((z1+EDGE)/edgeCell);
    let hit=false;
    for(let gx=gx0;gx<=gx1&&!hit;gx++)for(let gz=gz0;gz<=gz1&&!hit;gz++){
      const list=outerGrid.get(gx+':'+gz);if(!list)continue;
      for(let k=0;k<list.length;k++){
        const e=list[k];
        if(y>=e.highY-EPS||y<e.lowY-EPS)continue;
        if(e.x1+EDGE<x0||e.x0-EDGE>x1||e.z1+EDGE<z0||e.z0-EDGE>z1)continue;
        if(triCrosses(ax,az,bx,bz,cx,cz,e,0)||(coarse&&e.outer&&triCrosses(ax,az,bx,bz,cx,cz,e,EDGE))){hit=true;break;}
      }
    }
    if(hit){splitMask[f]=1;splitCount++;}
  }
  if(!splitCount)return null;
  const names=Object.keys(g.attributes).filter(n=>n!=='weatherOpen');
  const attrs=names.map(n=>g.attributes[n]);
  const offsets=[];let stride=3;
  for(const a of attrs){offsets.push(stride);stride+=a.itemSize;}
  const read=(idx,world)=>{
    const v=new Array(stride);
    v[0]=world.x;v[1]=world.y;v[2]=world.z;
    for(let a=0;a<attrs.length;a++)for(let k=0;k<attrs[a].itemSize;k++)v[offsets[a]+k]=attrs[a].getComponent(idx,k);
    return v;
  };
  const clipTri=(i0,i1,i2)=>{
    p0.fromBufferAttribute(posAttr,i0).applyMatrix4(effective);
    p1.fromBufferAttribute(posAttr,i1).applyMatrix4(effective);
    p2.fromBufferAttribute(posAttr,i2).applyMatrix4(effective);
    const v0=read(i0,p0),v1=read(i1,p1),v2=read(i2,p2);
    const x0=Math.min(p0.x,p1.x,p2.x),x1=Math.max(p0.x,p1.x,p2.x);
    const z0=Math.min(p0.z,p1.z,p2.z),z1=Math.max(p0.z,p1.z,p2.z);
    const y=(p0.y+p1.y+p2.y)/3,coarse=Math.max(x1-x0,z1-z0)>.45;
    let polys=[[v0,v1,v2]];
    for(const e of candidatesFor(x0,x1,z0,z1,y)){
      const next=[];
      for(const poly of polys){
        if(edgeCrosses(poly,e,0))next.push(...splitByLine(poly,e.a[0],e.a[1],e.nx,e.nz,0));
        else next.push(poly);
      }
      polys=next;
      if(e.outer&&coarse){
        const next2=[];
        for(const poly of polys){
          if(edgeCrosses(poly,e,EDGE))next2.push(...splitByLine(poly,e.a[0],e.a[1],e.nx,e.nz,EDGE));
          else next2.push(poly);
        }
        polys=next2;
      }
    }
    const tris=[];
    for(const poly of polys){
      if(polyXzArea(poly)<1e-6)continue;
      for(let i=1;i+1<poly.length;i++){
        const a=poly[0],b=poly[i],c=poly[i+1];
        if(Math.abs((b[0]-a[0])*(c[2]-a[2])-(c[0]-a[0])*(b[2]-a[2]))*.5<1e-6)continue;
        tris.push([a,b,c]);
      }
    }
    return tris;
  };
  // Indexed path (e.g. terrain lawn): keep every original vertex & unsplit
  // triangle index untouched; append only the newly created split vertices.
  if(index&&!sortedRanges&&!(g.groups&&g.groups.length)){
    const origVerts=posAttr.count,extra=attrs.map(()=>[]),newIndices=[];
    let nextVert=origVerts;
    for(let f=0;f<triCount;f++){
      const i0=index.getX(f*3),i1=index.getX(f*3+1),i2=index.getX(f*3+2);
      if(!splitMask[f]){newIndices.push(i0,i1,i2);continue;}
      for(const [a,b,c] of clipTri(i0,i1,i2)){
        for(const v of [a,b,c]){
          for(let k=0;k<attrs.length;k++)for(let cIdx=0;cIdx<attrs[k].itemSize;cIdx++)extra[k].push(v[offsets[k]+cIdx]);
          newIndices.push(nextVert++);
        }
      }
    }
    const clipped=new THREE.BufferGeometry();
    names.forEach((name,k)=>{
      const itemSize=attrs[k].itemSize,buf=new Float32Array(nextVert*itemSize);
      if(attrs[k].array instanceof Float32Array&&!attrs[k].isInterleavedBufferAttribute)buf.set(attrs[k].array,0);
      else for(let i=0;i<origVerts;i++)for(let cIdx=0;cIdx<itemSize;cIdx++)buf[i*itemSize+cIdx]=attrs[k].getComponent(i,cIdx);
      buf.set(extra[k],origVerts*itemSize);
      clipped.setAttribute(name,new THREE.Float32BufferAttribute(buf,itemSize,attrs[k].normalized));
    });
    clipped.setIndex(new THREE.BufferAttribute(nextVert>65535?new Uint32Array(newIndices):new Uint16Array(newIndices),1));
    clipped.name=g.name;clipped.userData={...g.userData};
    clipped.computeBoundingBox();clipped.computeBoundingSphere();
    return clipped;
  }
  const out=attrs.map(()=>[]);
  let writtenVerts=0;
  const emitTri=(a,b,c)=>{
    for(const v of [a,b,c])for(let k=0;k<attrs.length;k++)for(let cIdx=0;cIdx<attrs[k].itemSize;cIdx++)out[k].push(v[offsets[k]+cIdx]);
    writtenVerts+=3;
  };
  const emitRaw=(i0,i1,i2)=>{
    for(const idx of [i0,i1,i2])for(let k=0;k<attrs.length;k++)for(let cIdx=0;cIdx<attrs[k].itemSize;cIdx++)out[k].push(attrs[k].getComponent(idx,cIdx));
    writtenVerts+=3;
  };
  const newRanges=sortedRanges?sortedRanges.map(r=>({...r,start:0,count:0})):null;
  ri=0;let activeRange=-1;
  for(let f=0;f<triCount;f++){
    if(sortedRanges){
      while(ri<sortedRanges.length&&f*3>=sortedRanges[ri].start+sortedRanges[ri].count)ri++;
      const inRange=ri<sortedRanges.length&&f*3>=sortedRanges[ri].start?ri:-1;
      if(inRange!==activeRange){if(inRange>=0&&newRanges[inRange].count===0)newRanges[inRange].start=writtenVerts;activeRange=inRange;}
    }
    const before=writtenVerts;
    const i0=index?index.getX(f*3):f*3,i1=index?index.getX(f*3+1):f*3+1,i2=index?index.getX(f*3+2):f*3+2;
    if(!splitMask[f])emitRaw(i0,i1,i2);
    else for(const [a,b,c] of clipTri(i0,i1,i2))emitTri(a,b,c);
    if(activeRange>=0)newRanges[activeRange].count+=writtenVerts-before;
  }
  const clipped=new THREE.BufferGeometry();
  names.forEach((name,k)=>clipped.setAttribute(name,new THREE.Float32BufferAttribute(out[k],attrs[k].itemSize,attrs[k].normalized)));
  clipped.name=g.name;
  clipped.userData={...g.userData};
  if(newRanges){
    if(g.userData.snapRanges)clipped.userData.snapRanges=newRanges;
    if(o.userData.snapRanges)o.userData.snapRanges=newRanges;
  }
  clipped.computeBoundingBox();clipped.computeBoundingSphere();
  return clipped;
}

// Run only at generation, adoption, late import or editor deformation. Each
// instance has its own exposure; regular batches retain one float per vertex.
export function writeWeatherOpen(root,cover,worldScale=1) {
  root.updateWorldMatrix(true,true);
  const p=new THREE.Vector3(),n=new THREE.Vector3(),matrix=new THREE.Matrix4(),normal=new THREE.Matrix3(),effective=new THREE.Matrix4();
  root.traverse(o=>{
    if(o.userData?.syncBakeCover)o.userData.syncBakeCover(cover,worldScale,o.matrixWorld);
    if(!o.isMesh||!o.geometry?.attributes.position||o.layers.isEnabled(31))return;
    let g=o.geometry;
    const instanceExposure=o.userData.weatherInstanceColor?o.instanceColor:null;
    // Key on where the vertices actually land: a yard built unparented with
    // worldScale FT and then adopted under the twin root (scale FT, worldScale 1)
    // has the same effective transform, so adoption reuses the build's samples
    // instead of resampling every vertex (owner startup trace 2026-11-20). The
    // samples themselves are computed exactly as before.
    effective.makeScale(worldScale,worldScale,worldScale).multiply(o.matrixWorld);
    // Deeper children multiply in a different order before and after adoption;
    // ten significant digits absorb that last-bit difference (a miss resamples).
    const transform=[o.instanceMatrix?.version,...effective.elements.map(v=>+v.toPrecision(10))].join(',');
    const savedBase=unclipped.get(o);
    const sameClippedGeo=savedBase&&savedBase.clipped===g;
    const boundByAtlas=!!(savedBase&&!sameClippedGeo&&g.attributes.lmRoom);
    const isOurClipped=sameClippedGeo&&savedBase.clippedVersion===g.attributes.position.version;
    if(savedBase&&!isOurClipped&&!boundByAtlas)unclipped.delete(o);
    const baseGeo=isOurClipped||boundByAtlas?savedBase.base:g;
    const stamp=baseGeo.attributes.position.version+':'+g.attributes.position.version+':'+transform;
    const previous=written.get(o);
    if(previous?.geometry===g&&previous.attribute===(instanceExposure||g.attributes.weatherOpen)&&previous.stamp===stamp&&previous.coverKey===cover.key)return;
    if(!instanceExposure){
      const deformedInPlace=sameClippedGeo&&!isOurClipped;
      const roofChanged=!previous||previous.staticKey!==cover.staticKey;
      const shouldClip=!o.isInstancedMesh&&!deformedInPlace&&(boundByAtlas?roofChanged:(roofChanged||previous.stamp!==stamp));
      if(shouldClip){
        const origSnap=isOurClipped||boundByAtlas?savedBase.snapRanges:(o.userData.snapRanges?o.userData.snapRanges.map(r=>({...r})):null);
        if(origSnap&&o.userData.snapRanges)o.userData.snapRanges=origSnap.map(r=>({...r}));
        const clipped=clipHorizontalToCover(baseGeo,o,effective,cover);
        if(clipped){
          if(isOurClipped||boundByAtlas)g.dispose();
          // Building batches rebuild from scratch on roof edits, so only reused
          // yard ground/hardscape and non-merged meshes retain baseGeo.
          let yardPart=null;
          for(let p=o;p;p=p.parent)if(p.userData?.yardPart){yardPart=p.userData.yardPart;break;}
          if(!o.userData.merged||yardPart==='hardscape'||yardPart==='terrain')unclipped.set(o,{base:baseGeo,clipped,clippedVersion:clipped.attributes.position.version,snapRanges:origSnap});
          else unclipped.delete(o);
          g=o.geometry=clipped;
          owners.set(g,o.uuid);
        }else if(isOurClipped||boundByAtlas){
          g.dispose();
          g=o.geometry=baseGeo;
          if(origSnap)o.userData.snapRanges=origSnap.map(r=>({...r}));
          unclipped.delete(o);
        }
      }
      if(owners.has(g)&&owners.get(g)!==o.uuid)g=o.geometry=g.clone();
      owners.set(g,o.uuid);
    }
    const finalStamp=baseGeo.attributes.position.version+':'+g.attributes.position.version+':'+transform;
    // Grass has a camera-dependent count. Sample its full capacity so moving
    // closer never exposes an unsampled clump, without cloning blade geometry.
    const count=instanceExposure?o.instanceMatrix.count:o.isInstancedMesh?o.count:g.attributes.position.count;
    let attribute=instanceExposure||g.attributes.weatherOpen;
    if(!attribute||attribute.count!==count||!!attribute.isInstancedBufferAttribute!==!!o.isInstancedMesh) {
      attribute=new (o.isInstancedMesh?THREE.InstancedBufferAttribute:THREE.BufferAttribute)(new Float32Array(count),1);
      g.setAttribute('weatherOpen',attribute);
    }
    normal.getNormalMatrix(o.matrixWorld);
    const ranges=[...(o.userData.snapRanges||g.userData.snapRanges||[])].sort((a,b)=>a.start-b.start);
    let rangeIndex=0;
    // A room edit can change slab cover without changing any roof. Reuse the
    // static exposure, resampling it only for changed position ranges; dynamic
    // slabs still re-evaluate every potentially exposed receiver.
    const reuse=previous?.geometry===g&&previous.staticKey===cover.staticKey&&previous.transform===transform&&previous.base.length===count;
    const base=reuse?previous.base:new Float32Array(count),faces=reuse?previous.faces:new Uint8Array(count);
    const moved=!reuse||previous.positionVersion!==g.attributes.position.version;
    let dirty=null;
    if(reuse&&moved&&!o.isInstancedMesh&&g.attributes.position.updateRanges.length){
      dirty=new Uint8Array(count);
      for(const r of g.attributes.position.updateRanges)dirty.fill(1,Math.max(0,Math.floor(r.start/3)),Math.min(count,Math.ceil((r.start+r.count)/3)));
    }
    let updated=false;
    const position=i=>{
      if(o.isInstancedMesh){o.getMatrixAt(i,matrix);p.set(0,0,0).applyMatrix4(matrix).applyMatrix4(o.matrixWorld);}
      else p.fromBufferAttribute(g.attributes.position,i).applyMatrix4(o.matrixWorld);
      p.multiplyScalar(worldScale);
    };
    for(let i=0;i<count;i++) {
      while(rangeIndex<ranges.length&&i>=ranges[rangeIndex].start+ranges[rangeIndex].count)rangeIndex++;
      const sample=!reuse||moved&&(!dirty||dirty[i]);
      if(sample){
        position(i);
        const range=ranges[rangeIndex],kind=(range&&i>=range.start?range.kind:null)||o.userData.kind;
        const roofFace=!o.isInstancedMesh&&kind==='roof'&&g.attributes.normal&&n.fromBufferAttribute(g.attributes.normal,i).applyMatrix3(normal).normalize().y>.001;
        base[i]=cover.staticOpen(p.x,p.y,p.z,roofFace);faces[i]=roofFace?1:0;
      }
      let value=base[i];
      if(value&&!faces[i]){if(!sample)position(i);value*=cover.slabOpen(p.x,p.y,p.z);}
      if(attribute.getX(i)!==value){attribute.setX(i,value);updated=true;}
    }
    if(updated)attribute.needsUpdate=true;
    written.set(o,{geometry:g,attribute,stamp:finalStamp,coverKey:cover.key,staticKey:cover.staticKey,transform,base,faces,positionVersion:g.attributes.position.version});
  });
}

// Drag/settle can replace room triangles inside a retained material batch.
// Refresh only this building's slab snapshot before resampling exposure.
export function refreshSlabCover(root,plan,roofs,buildingId) {
  const b=plan.buildings?.find(b=>b.id===buildingId),surface=roofs.get(buildingId);
  if(!b||!surface)return;
  root.updateWorldMatrix(true,true);
  const frame=new THREE.Matrix4().makeRotationY((b.rotation||0)*Math.PI/180);
  frame.setPosition(b.position?.[0]||0,buildingBase(plan,b),-(b.position?.[1]||0));
  const inverse=frame.invert().multiply(new THREE.Matrix4().makeScale(1/FT,1/FT,1/FT));
  const positions=[],a=new THREE.Vector3(),c=new THREE.Vector3(),d=new THREE.Vector3(),n=new THREE.Vector3();
  root.traverse(o=>{
    if(!o.isMesh||o.layers.isEnabled(31)||!o.geometry?.attributes.position)return;
    const g=o.geometry,p=g.attributes.position,matrix=inverse.clone().multiply(o.matrixWorld);
    for(const r of o.userData.snapRanges||[{start:0,count:g.index?.count??p.count,...o.userData}]) {
      if(r.buildingId!==buildingId||!['floor','room'].includes(r.kind))continue;
      for(let i=r.start;i<r.start+r.count;i+=3) {
        for(const [v,j] of [[a,0],[c,1],[d,2]])v.fromBufferAttribute(p,g.index?g.index.getX(i+j):i+j).applyMatrix4(matrix);
        THREE.Triangle.getNormal(a,c,d,n);
        if(r.part==='ceiling'?Math.abs(n.y)<=.001:n.y<=.001)continue;
        for(const v of [a,c,d])positions.push(v.x,-v.z,v.y);
      }
    }
  });
  surface.slabPositions=positions;
}
