"""Shared runtime triangle checks for generated twin solids under Node."""

NORMAL_CHECKS = r"""
const trianglesOf=geometry=>{
 const p=geometry.attributes.position,ix=geometry.index,result=[];
 for(let i=0;i<(ix?.count??p.count);i+=3){
  const vertices=[0,1,2].map(j=>new THREE.Vector3().fromBufferAttribute(p,ix?ix.getX(i+j):i+j));
  const normal=new THREE.Vector3().crossVectors(vertices[1].clone().sub(vertices[0]),vertices[2].clone().sub(vertices[0]));
  if(normal.lengthSq()<1e-16)continue;
  result.push({vertices,normal:normal.normalize(),centre:vertices.reduce((s,v)=>s.add(v),new THREE.Vector3()).divideScalar(3)});
 }
 return result;
};
const checkBoundaryNormals=(geometry,outline,{holes=[],top,bottom,label='solid'}={})=>{
 const boundaries=[outline,...holes].map((poly,ring)=>{
  const sign=Math.sign(poly.reduce((s,p,i)=>{const q=poly[(i+1)%poly.length];return s+p[0]*q[1]-p[1]*q[0];},0))*(ring?-1:1);
  return poly.map((a,i)=>{const b=poly[(i+1)%poly.length],dx=b[0]-a[0],dy=b[1]-a[1];
   return {a,b,normal:new THREE.Vector3(sign*dy,0,sign*dx).normalize(),seen:0};});
 }).flat();
 let ups=0,downs=0,sides=0;
 for(const {vertices,normal} of trianglesOf(geometry)){
  if(Math.abs(normal.y)<1e-5){
   const edge=boundaries.find(({a,b})=>vertices.every(v=>{
    const dx=b[0]-a[0],dy=b[1]-a[1],t=((v.x-a[0])*dx+(-v.z-a[1])*dy)/(dx*dx+dy*dy);
    return t>=-1e-5&&t<=1+1e-5&&Math.abs(dx*(-v.z-a[1])-dy*(v.x-a[0]))<1e-4;
   }));
   assert.ok(edge,`${label}: side lies on a boundary`);
   assert.ok(normal.dot(edge.normal)>0,`${label}: side points outward at ${edge.a} -> ${edge.b}`);edge.seen++;sides++;
  }else if(top!==undefined&&vertices.every(v=>Math.abs(v.y-top)<1e-5)){
   assert.ok(normal.y>0,`${label}: top points up`);ups++;
  }else if(bottom!==undefined&&vertices.every(v=>Math.abs(v.y-bottom)<1e-5)){
   assert.ok(normal.y<0,`${label}: bottom points down`);downs++;
  }
 }
 assert.ok(sides&&boundaries.every(e=>e.seen),`${label}: all boundary edges checked`);
 if(top!==undefined)assert.ok(ups,`${label}: top checked`);
 if(bottom!==undefined)assert.ok(downs,`${label}: bottom checked`);
};
"""
