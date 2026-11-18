import * as THREE from 'three';
import { inPolygon, edgeDistance } from '../twin_ground.js';
import { waterBodies } from './water_ripples.js';
import { effectMesh } from './water_material.js';

export function buildVapour(fixture,{plan,origin,mist=false}) {
  const group=new THREE.Group(),anchors=[],positions=[],uvs=[],seeds=[],indices=[],bases=[];
  let width=3,body=null,spas=[];
  if(!mist) {
    const bodies=waterBodies(plan);body=bodies.find(b=>inPolygon(b.polygon,...origin));
    // A spa is heated on its own: pool steam stays off the spa, and a wisp's foot clear of its wall.
    if(body&&body===bodies[bodies.length-1])spas=bodies.slice(0,-1).map(b=>b.polygon);
  }
  if(body) {
    const xs=body.polygon.map(p=>p[0]),ys=body.polygon.map(p=>p[1]),x0=Math.min(...xs),y0=Math.min(...ys),dx=Math.max(...xs)-x0,dy=Math.max(...ys)-y0;
    const nx=Math.max(1,Math.min(12,Math.ceil(dx/2.5))),ny=Math.max(1,Math.min(12,Math.ceil(dy/2.5)));width=Math.max(dx/nx,dy/ny)*1.7;
    for(let x=0;x<nx;x++)for(let y=0;y<ny;y++) {
      const at=[x0+(x+.5)*dx/nx,y0+(y+.5)*dy/ny,body.height+.025];
      const clear=spas.every(spa=>!inPolygon(spa,...at)&&spa.every((a,i)=>edgeDistance(at,a,spa[(i+1)%spa.length])>=width*.35));
      if(clear&&inPolygon(body.polygon,...at))anchors.push(at.map((v,k)=>v-origin[k]));
    }
    if(!anchors.length)anchors.push([0,0,body.height+.025-origin[2]]);
  } else if(mist && fixture.path) {
    width=4.5;
    fixture.path.slice(1).forEach((b,i)=>{
      const a=fixture.path[i],count=Math.max(1,Math.ceil(Math.hypot(...b.map((v,k)=>v-a[k]))/1.5));
      for(let j=0;j<count;j++)anchors.push(a.map((v,k)=>v+(b[k]-v)*(j+.5)/count));
    });
  } else {if(mist)width=4.5;anchors.push([0,0,0]);}
  // Interleaved curved wisps avoid a single billboard silhouette. All layers
  // are batched; the fragment's falloff erases every boundary without depth taps.
  anchors.forEach((at,index)=>{
    for(let layer=0;layer<3;layer++) {
      const angle=layer*Math.PI/3+index*2.39996,offset=positions.length/3,rows=12;
      for(let j=0;j<=rows;j++)for(let side=0;side<2;side++) {
        const v=j/rows,u=side,spread=(u-.5)*width*(mist?.25+v*.75:.7+v*.3);
        const x=at[0]+Math.cos(angle)*spread,y=at[2],z=-at[1]+Math.sin(angle)*spread;
        positions.push(x,y,z);bases.push(x,y,z);uvs.push(u,v);seeds.push(index*.719+layer*3.17);
        if(j&&side){const k=offset+j*2+side;indices.push(k,k-1,k-3,k,k-3,k-2);}
      }
    }
  });
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setAttribute('uv',new THREE.Float32BufferAttribute(uvs,2));geometry.setAttribute('seed',new THREE.Float32BufferAttribute(seeds,1));geometry.setIndex(indices);
  // Premultiplied: steam scatters light into the view more than it blocks what
  // lies behind, so over lit water it brightens and never reads as dark smoke.
  const material=new THREE.ShaderMaterial({transparent:true,premultipliedAlpha:true,depthWrite:false,side:THREE.DoubleSide,forceSinglePass:true,toneMapped:false,
    uniforms:{time:{value:0},strength:{value:1},opacity:{value:1},light:{value:1},mist:{value:Number(mist)},glow:{value:new THREE.Color(0,0,0)}},
    vertexShader:`uniform float time; uniform float mist; attribute float seed; varying vec2 vUv; varying float vSeed; varying float vFacing;
      void main(){vUv=uv;vSeed=seed;vec3 p=position;
        float envelope=sin(uv.y*3.14159);
        p.x+=envelope*(sin(time*.21+seed+uv.y*4.)*.16+uv.y*.35);
        p.z+=envelope*cos(time*.17+seed+uv.y*3.)*.14;
        vec4 mv=modelViewMatrix*vec4(p,1.);vFacing=abs(dot(normalize(normalMatrix*normal),normalize(-mv.xyz)));
        gl_Position=projectionMatrix*mv;}`,
    fragmentShader:`uniform float time; uniform float strength; uniform float opacity; uniform float light; uniform float mist; uniform vec3 glow;
      varying vec2 vUv; varying float vSeed; varying float vFacing;
      float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
      float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+1.),f.x),f.y);}
      void main(){
        vec2 uv=vUv;float clock=time*mix(.2,.18,mist);
        // Steam breaks into fine filaments; mist drifts as broad cloud.
        vec2 p=vec2(uv.x*mix(5.5,2.2,mist)+vSeed,uv.y*mix(6.,2.4,mist)-clock);
        float n=noise(p+vec2(noise(p*.7+clock),0.))*.55+noise(p*2.07-vec2(clock*.3,clock))*.3+noise(p*4.13+clock*.5)*.15;
        float sides=pow(max(0.,sin(uv.x*3.14159)),mix(1.8,1.1,mist));
        // Steam hugs the water and thins fast as it rises, so most of it lies in the
        // lowest foot whatever the authored height; mist leaves a nozzle thin and
        // hangs as a cloud below it. Multisampling reads uv past a wisp's top edge:
        // a negative base there is not a number, and the lamp glow spreads it.
        float rise=smoothstep(0.,.04,uv.y)*exp(-uv.y*3.6)*max(0.,1.-uv.y);
        float height=mix(rise,smoothstep(0.,.3,uv.y)*pow(max(0.,1.-uv.y),.8),mist);
        float wisps=smoothstep(mix(.42,.08,mist),mix(.86,.74,mist),n);
        float alpha=sides*height*wisps*mix(.06+.1*strength,.32+.4*strength,mist)*smoothstep(0.,.3,vFacing)*opacity;
        // Lit by the sky, and from beneath by the water's own lamps when they are on.
        vec3 color=mix(mix(vec3(.82,.88,.92),vec3(.64,.72,.75),mist),mix(vec3(.97,.99,1.),vec3(.88,.93,.94),mist),n)*light
          +glow*(1.-uv.y)*(1.-mist);
        gl_FragColor=vec4(color*alpha,alpha*mix(.5,1.,mist));
      }`});
  const mesh=effectMesh(geometry,material);group.add(mesh);let previous;
  return {group,body,pose(size){
    if(size===previous)return;previous=size;
    const p=geometry.attributes.position;
    for(let i=0;i<p.count;i++)p.setXYZ(i,bases[i*3],bases[i*3+1]+uvs[i*2+1]*size*(mist?-1:1),bases[i*3+2]);
    p.needsUpdate=true;geometry.computeVertexNormals();geometry.computeBoundingSphere();geometry.boundingSphere.radius+=.6;
  }};
}
