import * as THREE from 'three';
import { spaAim, waterReach } from './water_ripples.js';
import { laminarMesh, impactPatch, finishPose } from './laminar.js';

export function buildSpaJet(plan,origin) {
  const aim=spaAim(plan,origin),group=new THREE.Group();
  if(!aim.body)return {group,pose(){}};
  const positions=[],uvs=[],parts=[],indices=[],rows=28,columns=12;
  for(let i=0;i<=rows;i++)for(let j=0;j<=columns;j++) {
    positions.push(0,0,0);uvs.push(j/columns,i/rows);parts.push(0);
    if(i&&j){const k=i*(columns+1)+j;indices.push(k,k-1,k-columns-2,k,k-columns-2,k-columns-1);}
  }
  const patch=impactPatch(positions,uvs,parts,indices),mesh=laminarMesh(positions,uvs,parts,indices);group.add(mesh);
  mesh.material.fragmentShader=mesh.material.fragmentShader.replace('if(sheet>.5)',`if(vPart<.5){
    float bubbles=smoothstep(.32,.74,noise(vec2(vUv.x*18.,vUv.y*13.-time*1.8))*.6+noise(vec2(vUv.x*41.,vUv.y*31.-time*3.))*.4);
    float envelope=sin(vUv.y*3.14159);
    color=mix(vec3(.23,.57,.63),vec3(.87,.96,.97),bubbles*.75);
    alpha=(.1+.48*bubbles)*envelope;
  }
  if(sheet>.5)`);
  let previous;
  return {group,aim,pose(size){
    if(size===previous)return;previous=size;
    const end=waterReach(aim,size),dx=end[0]-origin[0],dy=end[1]-origin[1],reach=Math.hypot(dx,dy)||1;
    const start=Math.min(origin[2],aim.body.height-.45),height=aim.body.height-origin[2],p=mesh.geometry.attributes.position;
    for(let i=0;i<=rows;i++)for(let j=0;j<=columns;j++) {
      const t=i/rows,a=j/columns*Math.PI*2,r=.045+Math.sin(t*Math.PI/2)*Math.min(.38,reach*.25);
      p.setXYZ(i*(columns+1)+j,dx*t-dy/reach*Math.cos(a)*r,Math.min(height-.025,start-origin[2]+(height-(start-origin[2]))*t+Math.sin(a)*r*.55),-dy*t-dx/reach*Math.cos(a)*r);
    }
    patch(p,end.map((v,k)=>v-origin[k]),.3+Math.min(reach,3)*.16);finishPose(mesh);
  }};
}
