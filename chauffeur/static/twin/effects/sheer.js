import * as THREE from 'three';
import { laminarMesh, finishPose } from './laminar.js';

export function buildSheer(fixture,{normals,drops}) {
  const group=new THREE.Group(),positions=[],uvs=[],parts=[],indices=[],rows=40,path=fixture.path;
  const distance=[0];path.slice(1).forEach((p,i)=>distance.push(distance[i]+Math.hypot(...p.map((v,k)=>v-path[i][k]))));
  const span=distance.at(-1)||1;
  // Extra rows at the landing form a narrow soft patch, in the same mesh.
  for(let i=0;i<path.length;i++)for(let j=0;j<=rows+2;j++) {
    positions.push(0,0,0);uvs.push(distance[i]/span,j<=rows?j/rows:(j-rows-1));parts.push(j>rows?1:0);
    if(i&&j&&j!==rows+1){const k=i*(rows+3)+j;indices.push(k,k-1,k-rows-4,k,k-rows-4,k-rows-3);}
  }
  const mesh=laminarMesh(positions,uvs,parts,indices,true);group.add(mesh);let previous;
  mesh.material.uniforms.grain.value.set(span*7,3);
  return {group,pose(size){
    if(size===previous)return;previous=size;
    const p=mesh.geometry.attributes.position;
    path.forEach((at,i)=>{for(let j=0;j<=rows+2;j++) {
      const foam=j>rows,t=foam?1:j/rows,spread=foam?(j-rows-1.5)*.65:0;
      const reach=size*Math.sin(t*Math.PI/2)+spread;
      p.setXYZ(i*(rows+3)+j,at[0]+normals[i][0]*reach,at[2]-drops[i]*t*t+(foam?.018:0),-at[1]-normals[i][1]*reach);
    }});finishPose(mesh);
  }};
}
