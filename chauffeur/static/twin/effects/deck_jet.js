import * as THREE from 'three';
import { groundAt } from '../twin_ground.js';
import { waterAim, waterReach } from './water_ripples.js';
import { laminarMesh, impactPatch, finishPose } from './laminar.js';

export function buildDeckJet(plan, origin) {
  const aim=waterAim(plan,origin,12),group=new THREE.Group(),positions=[],uvs=[],parts=[],indices=[],rows=48,columns=8;
  for(let i=0;i<=rows;i++)for(let j=0;j<=columns;j++) {
    positions.push(0,0,0);uvs.push(j/columns,i/rows);parts.push(0);
    if(i&&j){const k=i*(columns+1)+j;indices.push(k,k-1,k-columns-2,k,k-columns-2,k-columns-1);}
  }
  const patch=impactPatch(positions,uvs,parts,indices),mesh=laminarMesh(positions,uvs,parts,indices);group.add(mesh);
  let previous;
  return {group,aim,pose(size){
    if(size===previous)return;previous=size;
    const landing=waterReach(aim,size);if(!aim.body)landing[2]=groundAt(plan,...landing);
    const dx=landing[0]-origin[0],dz=-(landing[1]-origin[1]),dy=landing[2]-origin[2],reach=Math.hypot(dx,dz),arch=Math.max(.3,reach*.48);
    const p=mesh.geometry.attributes.position;
    for(let i=0;i<=rows;i++) {
      const t=i/rows,centre=new THREE.Vector3(dx*t,dy*t+4*arch*t*(1-t),dz*t);
      const tangent=new THREE.Vector3(dx,dy+4*arch*(1-2*t),dz).normalize();
      const side=new THREE.Vector3(-dz,0,dx).normalize(),up=new THREE.Vector3().crossVectors(tangent,side).normalize();
      for(let j=0;j<=columns;j++) {
        const angle=j/columns*Math.PI*2,radius=.045*(1-.3*t),v=centre.clone().addScaledVector(side,Math.cos(angle)*radius).addScaledVector(up,Math.sin(angle)*radius);
        p.setXYZ(i*(columns+1)+j,v.x,v.y,v.z);
      }
    }
    patch(p,landing.map((v,k)=>v-origin[k]),.35+Math.min(size,10)*.035);finishPose(mesh);
  }};
}
