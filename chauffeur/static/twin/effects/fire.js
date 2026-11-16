import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { fireFlameMaterial } from '../fire_pits.js';
import { effectMesh } from './water_material.js';

// Use the pit's unchanged flame shader, with two crossed rows in two draws.
export function buildFire(fixture) {
  const group = new THREE.Group(), path=fixture.path || [[0,0,0]], parts=[[],[]];
  const add=(p,phase) => {
    for(let side=0;side<2;side++) {
      const g=new THREE.PlaneGeometry(.7,1,4,12).translate(0,.5,0).rotateY(side*Math.PI/2);
      const data=new Float32Array(g.attributes.position.count*3),anchors=new Float32Array(data.length);
      for(let i=0;i<g.attributes.position.count;i++) {
        data[i*3]=phase*2.39996;anchors.set([p[0],p[2],-p[1]],i*3);
      }
      g.setAttribute('fireData',new THREE.Float32BufferAttribute(data,3));
      g.setAttribute('effectAnchor',new THREE.Float32BufferAttribute(anchors,3));
      g.translate(p[0],p[2],-p[1]); parts[side].push(g);
    }
  };
  if(fixture.path) {
    for(let i=1;i<path.length;i++) {
      const a=path[i-1],b=path[i],distance=Math.hypot(...b.map((v,k)=>v-a[k])),count=Math.max(1,Math.ceil(distance/.45));
      for(let j=0;j<count;j++)add(a.map((v,k)=>v+(b[k]-v)*(j+.5)/count),j);
    }
  } else add([0,0,0],0);
  for(const geometries of parts) {
    const material=fireFlameMaterial();
    material.uniforms.opacity={value:1};
    material.uniforms.height={value:1};material.uniforms.width={value:1};
    material.vertexShader=material.vertexShader.replace('uniform float time;', 'uniform float height; uniform float width; attribute vec3 effectAnchor; uniform float time;')
      .replace('vec3 p=position;', 'vec3 p=position; p.y-=effectAnchor.y*(1.-1./max(height,.00001)); p.xz=effectAnchor.xz+(p.xz-effectAnchor.xz)*width;');
    material.fragmentShader=material.fragmentShader.replace('uniform float time;', 'uniform float opacity; uniform float time;')
      .replace('float y=vUv.y;float x=vUv.x-.5;', 'float y=vUv.y;float x=vUv.x-.5; float phase=vFire.x;')
      .replace('y*12.-time*4.', 'y*12.-time*4.+phase')
      .replace('sin(time*2.)', 'sin(time*2.+phase)')
      .replace('time*9.+y*11.', 'time*9.+y*11.+phase')
      .replace('mask*pulse*.8','mask*pulse*.8*opacity');
    const mesh=effectMesh(mergeGeometries(geometries),material);geometries.forEach(g=>g.dispose());group.add(mesh);
    // Shader widths and sloped supports remain inside a conservative culling sphere.
    mesh.geometry.computeBoundingSphere();mesh.geometry.boundingSphere.radius+=40;
  }
  return {group,pose(size) {for(const mesh of group.children) {
    mesh.scale.y=size;mesh.material.uniforms.height.value=size;mesh.material.uniforms.width.value=.5+size*.5;
  }}};
}
