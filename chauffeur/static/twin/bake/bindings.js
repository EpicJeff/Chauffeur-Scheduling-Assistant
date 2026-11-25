// Project the stable bake topology onto the drawn material batches. Most faces
// are exact matches. Coplanar roof finish territories can retriangulate: clip
// those triangles against the neutral triangles, interpolating only attributes.
// Thus chart IDs/ownership and the geometry used by the baker never move.
import * as THREE from '../../vendor/three-r187/three.module.js';
import { isBakeRoot } from './source.js';

const pointKey = p => p.toArray().map(x => Math.round(x * 1e5)).join(',');
const faceKey = (role, p) => role + ':' + p.map(pointKey).sort().join('|');
const cell = 4;
const bindings = new WeakMap();
const compound = new WeakSet();
function domain(mesh, role=true) {
  const names=[];
  // Names up to (not including) the bake root: the drawn yard sits under the twin's
  // 'site' group and its neutral copy does not (v2.499.948-.962 lost every yard bake).
  for(let p=mesh;p && !p.isScene && !isBakeRoot(p);p=p.parent)if(p.name)names.push(p.name);
  return JSON.stringify([role?mesh.material.name:'@yard',mesh.userData.yardPart||null,names]);
}
function cells(points) {
  const lo = [0,1,2].map(i => Math.floor((Math.min(...points.map(p => p.getComponent(i))) - 1e-5) / cell));
  const hi = [0,1,2].map(i => Math.floor((Math.max(...points.map(p => p.getComponent(i))) + 1e-5) / cell));
  const out=[];
  for(let x=lo[0];x<=hi[0];x++)for(let y=lo[1];y<=hi[1];y++)for(let z=lo[2];z<=hi[2];z++)out.push(`${x},${y},${z}`);
  return out;
}
function overlap(points, target) {
  const normal = new THREE.Triangle(...target).getNormal(new THREE.Vector3());
  const own = new THREE.Triangle(...points).getNormal(new THREE.Vector3());
  if (normal.dot(own) < .99999 || points.some(p=>Math.abs(p.clone().sub(target[0]).dot(normal))>2e-5)) return [];
  let polygon=points;
  for(let e=0;e<3 && polygon.length>=3;e++) {
    const a=target[e], edge=target[(e+1)%3].clone().sub(a);
    const distance=p=>edge.clone().cross(p.clone().sub(a)).dot(normal);
    const next=[];
    for(let i=0;i<polygon.length;i++) {
      const p=polygon[i],q=polygon[(i+1)%polygon.length],dp=distance(p),dq=distance(q);
      if(dp>=-1e-10)next.push(p);
      if(dp>1e-10 && dq < -1e-10 || dp < -1e-10 && dq>1e-10)next.push(p.clone().lerp(q,dp/(dp-dq)));
    }
    polygon=next;
  }
  return polygon;
}

// Heightfield charts already define an affine top-down address space, independent
// of tessellation and height. Projecting Low's 2 ft cells onto High's triangles
// would subdivide the drawn grid (and miss non-coplanar grade transitions).
function bindHeightfield(mesh, charts, pageSize) {
  const g=mesh.geometry,p=g.attributes.position,count=p.count;
  const uv=new Float32Array(count*2),rooms=new Float32Array(count).fill(-1),pages=new Float32Array(count).fill(-1);
  const faces=new Map(),tiles=new Map(),x0=Math.min(...charts.map(c=>c.field[0])),y0=Math.min(...charts.map(c=>c.field[1]));
  for(const chart of charts) {
    tiles.set(`${Math.round((chart.field[0]-x0)/64)},${Math.round((chart.field[1]-y0)/64)}`,
      chart);
    faces.set(chart,[]);
  }
  const a=new THREE.Vector3(),b=a.clone(),c=a.clone(),n=a.clone(),point=a.clone();
  for(let f=0;f<count/3;f++) {
    a.fromBufferAttribute(p,f*3);b.fromBufferAttribute(p,f*3+1);c.fromBufferAttribute(p,f*3+2);
    n.subVectors(b,a).cross(point.subVectors(c,a));
    if(n.length()/2<1e-6 || Math.abs(n.normalize().y)<.25)continue;
    const tx=Math.floor(((a.x+b.x+c.x)/3-x0)/64),ty=Math.floor((-(a.z+b.z+c.z)/3-y0)/64);
    const chart=tiles.get(`${tx},${ty}`);if(!chart)continue;
    faces.get(chart).push(f);
    for(let k=0;k<3;k++) {
      const i=f*3+k;
      uv[i*2]=(chart.rect.x+(p.getX(i)-chart.field[0])*chart.density)/pageSize;
      uv[i*2+1]=(chart.rect.y+(-p.getZ(i)-chart.field[1])*chart.density)/pageSize;
      rooms[i]=chart.room;pages[i]=chart.page;
    }
  }
  g.setAttribute('uv3',new THREE.BufferAttribute(uv,2));
  g.setAttribute('lmRoom',new THREE.BufferAttribute(rooms,1));
  g.setAttribute('lmLightPage',new THREE.BufferAttribute(pages,1));
  return {mesh,faces};
}

export function bindReceivers(atlas, meshes, pageSize) {
  const sourceMeshes=[...new Set(atlas.room.charts.flatMap(c=>[c.mesh,...(c.proxies||[]).map(p=>p.mesh)]))];
  const sameArray=(a,b)=>a?.length===b?.length && a.every((v,i)=>v===b[i]);
  const matched=new Map(),heightfields=new Map(),unused=new Set(meshes);
  for(const source of sourceMeshes) {
    const match=[...unused].find(m=>domain(m)===domain(source) &&
      sameArray(m.matrixWorld.elements,source.matrixWorld.elements) &&
      sameArray(m.geometry.attributes.position.array,source.geometry.attributes.position.array) &&
      sameArray(m.geometry.attributes.normal?.array,source.geometry.attributes.normal?.array));
    if(match && (!source.geometry.userData.bakeHeightfield ||
        ['uv3','lmRoom','lmLightPage'].every(name=>source.geometry.attributes[name]))) {
      matched.set(source,match);unused.delete(match);continue;
    }
    if(source.geometry.userData.bakeHeightfield) {
      const mesh=[...unused].find(m=>m.geometry.userData.bakeHeightfield && domain(m)===domain(source) &&
        sameArray(m.matrixWorld.elements,source.matrixWorld.elements));
      if(mesh){heightfields.set(source,bindHeightfield(mesh,atlas.room.charts.filter(c=>c.mesh===source),pageSize));unused.delete(mesh);}
    }
  }
  // A drawn mesh identical to its source takes the source's attributes as they are,
  // even when others differ (a finished wall, or the yard beside a default house);
  // only the differing meshes are projected below.
  for(const [source,mesh] of matched)for(const name of ['uv3','lmRoom','lmLightPage']) {
    const attr=source.geometry.attributes[name];if(attr)mesh.geometry.setAttribute(name,attr.clone());
  }
  if(matched.size===sourceMeshes.length && !unused.size) {
    for(const chart of atlas.room.charts){chart.mesh=matched.get(chart.mesh);
      if(chart.proxies)chart.proxies=chart.proxies.map(p=>({...p,mesh:matched.get(p.mesh)}));
      bindings.set(chart.faces,[{mesh:chart.mesh,faces:chart.faces},...(chart.proxies||[]).map(p=>({...p,proxy:true}))]);}
    atlas.transportMeshes=meshes;
    return atlas;
  }
  const exact=new Map(), grid=new Map(), records=[];
  for(const chart of atlas.room.charts) {
    Object.defineProperty(chart,'receivers',{value:[], configurable:true});
    bindings.set(chart.faces,chart.receivers);
    compound.add(chart.faces);
    for(const part of [{mesh:chart.mesh,faces:chart.faces},...(chart.proxies||[])]) {
      const proxy=part.mesh!==chart.mesh || part.faces!==chart.faces, drawn=matched.get(part.mesh);
      const field=heightfields.get(part.mesh);
      if(field){const faces=field.faces.get(chart);if(faces?.length)chart.receivers.push({mesh:field.mesh,faces,proxy});continue;}
      if(drawn){chart.receivers.push({mesh:drawn,faces:part.faces,proxy});continue;}
      const g=part.mesh.geometry,role=domain(part.mesh);
      for(const f of part.faces) {
        const points=[0,1,2].map(k=>new THREE.Vector3().fromBufferAttribute(g.attributes.position,f*3+k).applyMatrix4(part.mesh.matrixWorld));
        const uv=[0,1,2].map(k=>new THREE.Vector2().fromBufferAttribute(g.attributes.uv3,f*3+k));
        const record={chart,points,uv,proxy,
          normal:new THREE.Triangle(...points).getNormal(new THREE.Vector3())};
        records.push(record);
        const key=faceKey(role,points);
        if(!exact.has(key))exact.set(key,[]);exact.get(key).push(record);
        record.role=role;
        if(part.mesh.userData.yardPart){record.alias=domain(part.mesh,false);const key=faceKey(record.alias,points);
          if(!exact.has(key))exact.set(key,[]);exact.get(key).push(record);}
      }
    }
  }
  for(const mesh of unused) {
    const old=mesh.geometry,attrs=Object.entries(old.attributes).filter(([k])=>!['uv3','lmRoom','lmLightPage','uv2','lmSkyPage'].includes(k));
    const output=attrs.map(()=>[]),uv=[],rooms=[],pages=[],byChart=new Map(),inverse=mesh.matrixWorld.clone().invert();
    const bary=new THREE.Vector3(),world=new THREE.Vector3();let written=0;
    const sourceRanges=old.userData.snapRanges||mesh.userData.snapRanges,snapRanges=[];
    let rangeIndex=0,currentRange=null,previousRange=null;
    const emit=(points,record,original,indices)=>{
      const triangle=new THREE.Triangle(...original),target=record&&new THREE.Triangle(...record.points);
      for(let i=1;i+1<points.length;i++) {
        const tri=[points[0],points[i],points[i+1]];
        if(new THREE.Triangle(...tri).getArea()<1e-12)continue;
        if(record){if(!byChart.has(record.chart))byChart.set(record.chart,{main:[],proxy:[]});
          byChart.get(record.chart)[record.proxy?'proxy':'main'].push(written/3);}
        for(const p of tri) {
          triangle.getBarycoord(p,bary);
          const originalIndex=original.indexOf(p);
          attrs.forEach(([name,a],j)=>{
            if(originalIndex>=0)for(let k=0;k<a.itemSize;k++)output[j].push(a.getComponent(indices[originalIndex],k));
            else if(name==='position'){world.copy(p).applyMatrix4(inverse);output[j].push(...world.toArray());}
            else for(let k=0;k<a.itemSize;k++)output[j].push(bary.x*a.getComponent(indices[0],k)+bary.y*a.getComponent(indices[1],k)+bary.z*a.getComponent(indices[2],k));
          });
          if(record){target.getBarycoord(p,bary);uv.push(...new THREE.Vector2().addScaledVector(record.uv[0],bary.x).addScaledVector(record.uv[1],bary.y).addScaledVector(record.uv[2],bary.z).toArray());}
          else uv.push(0,0);
          rooms.push(record?.chart.room??-1);pages.push(record?.chart.page??-1);written++;
        }
        if(currentRange) {
          if(currentRange===previousRange)snapRanges.at(-1).count+=3;
          else snapRanges.push({...currentRange,start:written-3,count:3});
          previousRange=currentRange;
        } else previousRange=null;
      }
    };
    for(let f=0;f<old.attributes.position.count/3;f++) {
      if(sourceRanges?.length) {
        while(rangeIndex+1<sourceRanges.length&&sourceRanges[rangeIndex].start+sourceRanges[rangeIndex].count<=f*3)rangeIndex++;
        const r=sourceRanges[rangeIndex];currentRange=f*3>=r.start&&f*3<r.start+r.count?r:null;
      }
      const indices=[f*3,f*3+1,f*3+2],points=indices.map(i=>new THREE.Vector3().fromBufferAttribute(old.attributes.position,i).applyMatrix4(mesh.matrixWorld));
      const normal=new THREE.Triangle(...points).getNormal(new THREE.Vector3());
      const role=domain(mesh),alias=mesh.userData.yardPart&&domain(mesh,false);
      const direct=(exact.get(faceKey(role,points))||alias&&exact.get(faceKey(alias,points)))?.find(r=>r.normal.dot(normal)>.99999);
      if(direct){emit(points,direct,points,indices);continue;}
      if(!grid.size)for(const record of records)for(const c of cells(record.points)) {
        const key=record.role+':'+c;if(!grid.has(key))grid.set(key,[]);grid.get(key).push(record);
        if(record.alias){const key=record.alias+':'+c;if(!grid.has(key))grid.set(key,[]);grid.get(key).push(record);}
      }
      const candidates=new Set(cells(points).flatMap(c=>grid.get(role+':'+c)||alias&&grid.get(alias+':'+c)||[]));
      let found=false;
      for(const record of candidates) {
        const polygon=overlap(points,record.points);
        if(polygon.length<3)continue;
        emit(polygon,record,points,indices);found=true;
      }
      if(!found)emit(points,null,points,indices);
    }
    const geometry=new THREE.BufferGeometry();
    attrs.forEach(([name,a],j)=>geometry.setAttribute(name,new THREE.Float32BufferAttribute(output[j],a.itemSize,a.normalized)));
    geometry.setAttribute('uv3',new THREE.Float32BufferAttribute(uv,2));
    geometry.setAttribute('lmRoom',new THREE.Float32BufferAttribute(rooms,1));
    geometry.setAttribute('lmLightPage',new THREE.Float32BufferAttribute(pages,1));
    geometry.userData={...old.userData};
    if(sourceRanges)geometry.userData.snapRanges=mesh.userData.snapRanges=snapRanges;
    mesh.geometry=geometry;old.dispose();
    for(const [chart,groups] of byChart)for(const [kind,faces] of Object.entries(groups))if(faces.length)
      chart.receivers.push({mesh,faces,proxy:kind==='proxy'});
  }
  return atlas;
}

export function materialParts(chart) { return bindings.get(chart.faces) || [{mesh:chart.mesh,faces:chart.faces},...(chart.proxies||[])]; }
export const boundMaterials = chart => bindings.has(chart.faces);
export function chartReflectance(chart) {
  if(!compound.has(chart.faces)) {
    const c=chart.mesh.material.color;return c?(c.r+c.g+c.b)/3:.5;
  }
  let sum=0,area=0;
  for(const {mesh,faces,proxy} of materialParts(chart)) {
    if(proxy)continue;
    const p=mesh.geometry.attributes.position,c=mesh.material.color;
    const reflectance=c?(c.r+c.g+c.b)/3:.5;
    for(const f of faces) {
      const tri=new THREE.Triangle(...[0,1,2].map(k=>new THREE.Vector3().fromBufferAttribute(p,f*3+k).applyMatrix4(mesh.matrixWorld)));
      const a=tri.getArea();area+=a;sum+=a*reflectance;
    }
  }
  return area?sum/area:.5;
}
