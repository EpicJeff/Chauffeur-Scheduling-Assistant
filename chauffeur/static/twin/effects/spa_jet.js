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
  // The plume meanders and swells over time, differently for every jet, held at
  // the jet and at its boil (the ends of uv.y).
  const plumeVertex='vec4 p=modelViewMatrix*vec4(position,1.);';
  if(!mesh.material.vertexShader.includes(plumeVertex))throw new Error('Spa jet shader missing anchor');
  mesh.material.vertexShader='uniform float time;\n'+mesh.material.vertexShader.replace(plumeVertex,`vec3 q=position;
        if(part<.5){
          float seed=dot(modelMatrix[3].xyz,vec3(1.7,9.2,4.1)),held=uv.y*(1.-uv.y)*4.;
          q+=vec3(sin(time*1.1+uv.y*6.+seed),.6*sin(time*.8+uv.y*4.3+seed*1.7),cos(time*1.3+uv.y*5.1+seed*.6))*.26*held;
          q+=vec3(sin(uv.x*6.28318*2.+time*2.+seed),0.,cos(uv.x*6.28318*3.-time*1.6+seed))*.07*held;
        }
        vec4 p=modelViewMatrix*vec4(q,1.);`);
  mesh.material.fragmentShader=mesh.material.fragmentShader.replace('if(sheet>.5)',`if(vPart<.5){
    // A loose cloud of fine bubbles, tinted by the water: it breaks into drifting
    // patches and fades where seen edge-on, never a solid white lobe (user,
    // 2026-11-17: "very regular and defined. Also very white").
    float bubbles=smoothstep(.5,.85,noise(vec2(vUv.x*36.,vUv.y*26.-time*2.4))*.6+noise(vec2(vUv.x*80.,vUv.y*60.-time*3.6))*.4);
    float patches=smoothstep(.3,.75,noise(vec2(vUv.x*5.+vUv.y*2.,vUv.y*4.-time*1.3))*.7+noise(vec2(vUv.x*11.,vUv.y*9.-time*2.))*.3);
    float face=smoothstep(.08,.75,abs(dot(normalize(vNormal),normalize(vView))));
    float envelope=sin(vUv.y*3.14159);
    color=mix(vec3(.62,.84,.9),vec3(.88,.96,.98),bubbles*.6);
    alpha=(.03+.22*bubbles)*patches*face*envelope;
  }
  if(sheet>.5)`).replace('// The lamps in the water it runs in light it',`if(vPart>.5){
    // A jet's boil: water wells up over the jet, bubbling and spreading out
    // from it. Soft, mostly broken white, densest over the jet.
    // Two layers cross-fade as their pattern grows, so the bubbles spread outward
    // with no seam and no rays from the centre.
    vec2 p=vUv*2.-1.;float r=length(p);
    float ta=fract(time*.35),tb=fract(time*.35+.5),wa=1.-abs(2.*ta-1.);
    float boilA=noise(p*(7.-3.*ta)+13.)*.6+noise(p*(16.-7.*ta)+31.)*.4;
    float boilB=noise(p*(7.-3.*tb)+57.)*.6+noise(p*(16.-7.*tb)+71.)*.4;
    float boil=mix(boilB,boilA,wa);
    float bubbles=smoothstep(.45,.82,boil);
    color=mix(vec3(.6,.82,.88),vec3(.95,.99,1.),bubbles);
    alpha=(bubbles*.5+.12)*(1.-smoothstep(.3,1.,r))*(.55+.45*strength);
  }
  // The lamps in the water it runs in light it`);
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
