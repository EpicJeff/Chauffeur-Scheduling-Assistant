import * as THREE from 'three';
import { buildingBase, buildingFootprint, inPolygon, edgeDistance } from '../twin_ground.js';
import { roofMesh } from '../twin_roof.js';

const FT=.3048, EDGE=.6, EPS=.002;
const owners=new WeakMap();
const written=new WeakMap();
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
    const surfaces=roofs.get(b.id),roofPositions=surfaces?.coverPositions||roofMesh(b.roof?.sections||[]).positions;
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
  const staticKey=JSON.stringify(staticParts),key=staticKey+'|'+JSON.stringify(dynamicParts);
  return {key,staticKey,open,slabOpen,staticOpen:(x,y,z,roofFace)=>open(x,y,z,roofFace,false),interior,roofHeight,blocked:(x,y,z)=>open(x,y,z)===0};
}

// Run only at generation, adoption, late import or editor deformation. Each
// instance has its own exposure; regular batches retain one float per vertex.
export function writeWeatherOpen(root,cover,worldScale=1) {
  root.updateWorldMatrix(true,true);
  const p=new THREE.Vector3(),n=new THREE.Vector3(),matrix=new THREE.Matrix4(),normal=new THREE.Matrix3();
  root.traverse(o=>{
    if(!o.isMesh||!o.geometry?.attributes.position||o.layers.isEnabled(31))return;
    let g=o.geometry;
    const transform=[o.instanceMatrix?.version,worldScale,...o.matrixWorld.elements].join(',');
    const stamp=g.attributes.position.version+':'+transform;
    const previous=written.get(o);
    if(previous?.geometry===g&&previous.attribute===g.attributes.weatherOpen&&previous.stamp===stamp&&previous.coverKey===cover.key)return;
    if(owners.has(g)&&owners.get(g)!==o.uuid)g=o.geometry=g.clone();
    owners.set(g,o.uuid);
    const count=o.isInstancedMesh?o.count:g.attributes.position.count;
    let attribute=g.attributes.weatherOpen;
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
    written.set(o,{geometry:g,attribute,stamp,coverKey:cover.key,staticKey:cover.staticKey,transform,base,faces,positionVersion:g.attributes.position.version});
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
