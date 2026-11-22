// Alpha classification is geometry (owner ruling, 2026-11-19). Remove the
// non-opaque receiving set from the neutral topology, without importing any
// material identity, tint or UV into it. Whole semantic pieces are the common
// case; mixed wall faces/roof territories use planar polygon subtraction.
import * as THREE from '../../vendor/three-r187/three.module.js';

function domain(mesh) {
  const names=[];for(let p=mesh;p;p=p.parent)if(p.name && !p.isScene && !p.userData.viewingWalls)names.push(p.name);
  return JSON.stringify([mesh.userData.yardPart||null,names]);
}
const owner=(d,r)=>d+':'+JSON.stringify([r?.buildingId||null,r?.pieceId||null,r?.bakePart||r?.part||null]);
const piece=(d,r)=>d+':'+JSON.stringify([r?.buildingId||null,r?.pieceId||null]);
const area=p=>Math.abs(p.reduce((s,a,i)=>{const b=p[(i+1)%p.length];return s+a[0]*b[1]-b[0]*a[1];},0))/2;
const cross=(a,b,p)=>(b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]);
function subtract(polygon,cutter) {
  if(cross(cutter[0],cutter[1],cutter[2])<0)cutter=[...cutter].reverse();
  const outside=[];let rest=polygon;
  for(let e=0;e<cutter.length && rest.length>=3;e++) {
    const yes=[],no=[],a=cutter[e],b=cutter[(e+1)%cutter.length];
    for(let i=0;i<rest.length;i++) {
      const p=rest[i],q=rest[(i+1)%rest.length],dp=cross(a,b,p),dq=cross(a,b,q);
      if(dp>=-1e-9)yes.push(p);if(dp<=1e-9)no.push(p);
      if(dp>1e-9 && dq < -1e-9 || dp < -1e-9 && dq>1e-9) {
        const t=dp/(dp-dq),v=p.map((x,k)=>x+t*(q[k]-x));yes.push(v);no.push(v);
      }
    }
    if(no.length>=3 && area(no)>1e-10)outside.push(no);rest=yes;
  }
  return outside;
}
function hull(points) {
  const sorted=[...new Map(points.map(p=>[p.map(x=>Math.round(x*1e8)).join(),p])).values()].sort((a,b)=>a[0]-b[0]||a[1]-b[1]);
  const half=list=>{const out=[];for(const p of list){while(out.length>1&&cross(out.at(-2),out.at(-1),p)<=1e-9)out.pop();out.push(p);}return out.slice(0,-1);};
  return half(sorted).concat(half([...sorted].reverse()));
}
function join(pieces) {
  pieces=pieces.filter(p=>p.length>=3&&area(p)>1e-10);
  let again=true;
  while(again){again=false;outer:for(let i=0;i<pieces.length;i++)for(let j=i+1;j<pieces.length;j++){
    const h=hull([...pieces[i],...pieces[j]]);
    if(Math.abs(area(h)-area(pieces[i])-area(pieces[j]))>1e-8)continue;
    pieces[i]=h;pieces.splice(j,1);again=true;break outer;
  }}
  return pieces.sort((a,b)=>JSON.stringify(a).localeCompare(JSON.stringify(b)));
}
const nonOpaque=m=>m.name==='glass'||m.alphaTest>0||m.transparent&&!m.userData.viewingOpaque;
function staticMesh(m) {
  return m.isMesh&&!Array.isArray(m.material)&&!m.layers.isEnabled(31)&&
    (m.userData.merged||m.geometry?.userData.bakeHeightfield)&&!m.geometry.userData.bakeExcluded&&
    m.material.name!=='fixture';
}
export function filterAlphaSource(source,root) {
  const domains=new Set();source.traverse(m=>{if(staticMesh(m))domains.add(domain(m));});
  const classes=new Map(),alpha=new Map();
  root.traverse(mesh=>{
    if(!staticMesh(mesh))return;
    const d=domain(mesh);if(!domains.has(d))return;
    const excluded=!!nonOpaque(mesh.material),g=mesh.geometry;
    const ranges=g.userData.snapRanges||mesh.userData.snapRanges||[{start:0,count:g.index?.count||g.attributes.position.count}];
    for(const r of ranges){const key=owner(d,r);if(!classes.has(key))classes.set(key,new Set());classes.get(key).add(excluded);}
    if(!excluded)return;
    if(!alpha.has(d))alpha.set(d,[]);
    const p=g.attributes.position,index=g.index,count=(index?.count||p.count)/3;
    let ri=0;for(let f=0;f<count;f++) {
      while(ri+1<ranges.length&&ranges[ri].start+ranges[ri].count<=f*3)ri++;
      const points=[0,1,2].map(k=>new THREE.Vector3().fromBufferAttribute(p,index?index.getX(f*3+k):f*3+k).applyMatrix4(mesh.matrixWorld));
      const tri=new THREE.Triangle(...points),normal=tri.getNormal(new THREE.Vector3());
      if(tri.getArea()>1e-12)alpha.get(d).push({points,normal,piece:piece(d,ranges[ri]),bounds:new THREE.Box3().setFromPoints(points).expandByScalar(.16)});
    }
  });
  source.traverse(mesh=>{
    if(!staticMesh(mesh))return;
    const d=domain(mesh),old=mesh.geometry,attrs=Object.entries(old.attributes),output=attrs.map(()=>[]);
    const ranges=old.userData.snapRanges||mesh.userData.snapRanges||[{start:0,count:old.index?.count||old.attributes.position.count}];
    const wasExcluded=nonOpaque(mesh.material);
    if(wasExcluded ? !ranges.some(r=>classes.get(owner(d,r))?.has(false)) : !alpha.has(d))return;
    if(!wasExcluded&&!ranges.some(r=>{
      const state=classes.get(owner(d,r));
      return state ? state.has(true) : alpha.get(d).some(cut=>cut.piece===piece(d,r));
    }))return;
    const inverse=mesh.matrixWorld.clone().invert(),bary=new THREE.Vector3(),p=old.attributes.position;
    const count=(old.index?.count||p.count)/3;let ri=0;
    for(let f=0;f<count;f++) {
      while(ri+1<ranges.length&&ranges[ri].start+ranges[ri].count<=f*3)ri++;
      const state=classes.get(owner(d,ranges[ri]));
      if(state?.size===1&&state.has(true))continue;
      if(wasExcluded&&(!state||!state.has(false)))continue;
      const indices=[0,1,2].map(k=>old.index?old.index.getX(f*3+k):f*3+k);
      const points=indices.map(i=>new THREE.Vector3().fromBufferAttribute(p,i).applyMatrix4(mesh.matrixWorld));
      const tri=new THREE.Triangle(...points),normal=tri.getNormal(new THREE.Vector3());
      let polygons=null;
      if(!state || state.has(true)) {
        const box=new THREE.Box3().setFromPoints(points),origin=points[0],u=points[1].clone().sub(origin).normalize(),v=normal.clone().cross(u);
        const project=p=>{const q=p.clone().sub(origin);return [q.dot(u),q.dot(v)];};
        let pieces=[points.map(project)];
        for(const cut of alpha.get(d)||[]) {
          if(cut.piece!==piece(d,ranges[ri])||normal.dot(cut.normal)<.99999||!box.intersectsBox(cut.bounds)||
            cut.points.some(p=>Math.abs(p.clone().sub(origin).dot(normal))>.16))continue;
          pieces=pieces.flatMap(piece=>subtract(piece,cut.points.map(project)));
          if(!pieces.length)break;
        }
        polygons=join(pieces).map(poly=>poly.map(p=>origin.clone().addScaledVector(u,p[0]).addScaledVector(v,p[1])));
      }
      for(const poly of polygons||[points])for(let j=1;j+1<poly.length;j++)for(const point of [poly[0],poly[j],poly[j+1]]) {
        const exact=points.indexOf(point);tri.getBarycoord(point,bary);
        attrs.forEach(([name,a],n)=>{
          if(exact>=0)for(let k=0;k<a.itemSize;k++)output[n].push(a.getComponent(indices[exact],k));
          else if(name==='position')output[n].push(...point.clone().applyMatrix4(inverse).toArray());
          else for(let k=0;k<a.itemSize;k++)output[n].push(bary.x*a.getComponent(indices[0],k)+bary.y*a.getComponent(indices[1],k)+bary.z*a.getComponent(indices[2],k));
        });
      }
    }
    const geometry=new THREE.BufferGeometry();attrs.forEach(([name,a],i)=>geometry.setAttribute(name,new THREE.Float32BufferAttribute(output[i],a.itemSize,a.normalized)));
    geometry.userData={...old.userData};
    // A fully removed batch contributes no opaque geometry, just like an
    // excluded original cutout batch. Its material/batch identity is irrelevant.
    if(!geometry.attributes.position.count)geometry.userData.bakeExcluded=true;
    mesh.geometry=geometry;old.dispose();
    if(wasExcluded&&geometry.attributes.position.count) {
      mesh.material=mesh.material.clone();mesh.material.transparent=false;mesh.material.opacity=1;mesh.material.alphaTest=0;
      mesh.material.depthWrite=true;mesh.material.userData.alphaMode='opaque';
      if(mesh.material.name==='glass')mesh.material.name='pane';
    }
  });
}
