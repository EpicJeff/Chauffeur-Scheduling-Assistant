import * as THREE from 'three';
import { effectMesh, waterMaterial } from './water_material.js';

function sheet(path, normals, drops, foam = false) {
  const positions=[],uvs=[],outward=[],indices=[],rows=foam?4:32;
  const total=path.slice(1).reduce((s,p,i)=>s+Math.hypot(...p.map((v,k)=>v-path[i][k])),0)||1;
  let distance=0;
  path.forEach((p,i)=>{
    if(i)distance+=Math.hypot(...p.map((v,k)=>v-path[i-1][k]));
    for(let j=0;j<=rows;j++) {
      const v=j/rows,n=normals[i],fall=foam?1:v;
      const spread=foam?(v-.5)*.8:0;
      positions.push(p[0]+n[0]*spread,p[2]-drops[i]*fall*fall+(foam?.02:0),-p[1]-n[1]*spread);
      uvs.push(distance/total,v);outward.push(n[0],0,-n[1]);
      if(i&&j){const b=i*(rows+1)+j;indices.push(b,b-1,b-rows-2,b,b-rows-2,b-rows-1);}
    }
  });
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));
  geometry.setAttribute('outward',new THREE.Float32BufferAttribute(outward,3));
  geometry.setIndex(indices);geometry.computeVertexNormals();
  const material=waterMaterial(foam?3:2);
  // Streak width is in feet, whatever the length of the lip.
  material.uniforms.span.value=total;
  if(foam)material.vertexShader=material.vertexShader.replace('if(kind>1.5 && kind<2.5)', 'if(kind>1.5)')
    .replace('(1.-exp(-uv.y*6.))','(1.-exp(-6.))');
  const mesh=effectMesh(geometry,material);
  // The vertex shader moves the sheet outward; use conservative culling bounds.
  geometry.computeBoundingSphere();geometry.boundingSphere.radius+=20;
  return mesh;
}

export function buildWaterfall(fixture, {normals, drops}) {
  const group=new THREE.Group();
  const body=sheet(fixture.path,normals,drops),foam=sheet(fixture.path,normals,drops,true);group.add(body,foam);
  return {group,pose(size) {
    for(const mesh of group.children)mesh.material.uniforms.flow.value=.08+size*.6;
  }};
}
