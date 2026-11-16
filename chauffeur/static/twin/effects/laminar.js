import * as THREE from 'three';
import { effectMesh } from './water_material.js';

// Clear water and its breaking edge share a draw. Streaks run with the flow
// (never bands across it) and a fixed sheen stands in for a reflection, so the
// water reads as glass without sampling the scene or adding a rendering pass.
export function laminarMesh(positions, uvs, parts, indices, sheet = false) {
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));
  geometry.setAttribute('part',new THREE.Float32BufferAttribute(parts,1));
  geometry.setIndex(indices);
  const material=new THREE.ShaderMaterial({transparent:true,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,toneMapped:false,
    uniforms:{time:{value:0},strength:{value:1},opacity:{value:1},light:{value:1},sheet:{value:Number(sheet)},grain:{value:new THREE.Vector2(4,6)}},
    vertexShader:`attribute float part; varying vec2 vUv; varying float vPart; varying vec3 vNormal; varying vec3 vView;
      void main(){vUv=uv;vPart=part;vNormal=normalMatrix*normal;vec4 p=modelViewMatrix*vec4(position,1.);vView=-p.xyz;gl_Position=projectionMatrix*p;}`,
    fragmentShader:`uniform float time; uniform float strength; uniform float opacity; uniform float light; uniform float sheet; uniform vec2 grain;
      varying vec2 vUv; varying float vPart; varying vec3 vNormal; varying vec3 vView;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+1.),f.x),f.y);}
      void main(){
        vec3 n=normalize(vNormal);
        float fres=pow(clamp(1.-abs(dot(n,normalize(vView))),0.,1.),2.5);
        float streak=noise(vec2(vUv.x*grain.x,vUv.y*grain.y-time*1.6));
        float glint=smoothstep(.6,.95,streak);
        float sheen=pow(abs(dot(n,normalize(vec3(.25,.85,.45)))),18.);
        vec3 color=mix(vec3(.42,.7,.78),vec3(.9,.97,.99),clamp(fres*.8+glint*.25+sheen*.7,0.,1.));
        // A jet is a thin rod: it needs more body than a sheet to read at yard distance.
        float alpha=.13+(1.-sheet)*.24+fres*.45+glint*.08+sheen*.4;
        color=mix(color,vec3(.86,.95,.98),(1.-sheet)*.45);
        if(sheet>.5){
          float edge=pow(abs(vUv.x*2.-1.),12.);color+=vec3(.12,.14,.14)*edge;alpha+=edge*.3;
          // The sheet thins and tears toward the landing.
          float tear=smoothstep(.55,1.,vUv.y)*noise(vec2(vUv.x*grain.x*.6,vUv.y*9.-time*3.));
          color=mix(color,vec3(.94,.98,1.),tear*.7);alpha+=tear*.3;
        }
        if(vPart>.5){
          float r=sheet>.5?abs(vUv.y*2.-1.):length(vUv*2.-1.);
          float spray=noise(vec2(vUv.x*37.,vUv.y*13.-time*2.))*.65+(.5+.5*sin(r*42.-time*6.))*.35;
          color=mix(vec3(.51,.75,.8),vec3(.94,.98,1.),spray);
          alpha=exp(-r*r*4.)*(1.-smoothstep(.6,1.,r))*(.25+.4*spray);
          if(sheet>.5)alpha*=smoothstep(0.,.03,vUv.x)*(1.-smoothstep(.97,1.,vUv.x));
        }
        gl_FragColor=vec4(color*light,min(.92,alpha*opacity));
      }`});
  return effectMesh(geometry,material);
}

export function impactPatch(positions,uvs,parts,indices) {
  const offset=positions.length/3;
  for(const [x,y] of [[0,0],[1,0],[1,1],[0,1]]){positions.push(0,0,0);uvs.push(x,y);parts.push(1);}
  indices.push(offset,offset+1,offset+2,offset,offset+2,offset+3);
  return (attribute,point,radius)=>{
    [[-1,-1],[1,-1],[1,1],[-1,1]].forEach(([x,z],i)=>attribute.setXYZ(offset+i,point[0]+x*radius,point[2]+.018,-point[1]+z*radius));
  };
}

export function finishPose(mesh) {
  mesh.geometry.attributes.position.needsUpdate=true;
  mesh.geometry.computeVertexNormals();mesh.geometry.computeBoundingSphere();
}
