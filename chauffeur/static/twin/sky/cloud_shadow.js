import * as THREE from 'three';
import { sampleCloudDensity } from './clouds.js';
import { createNoiseVolumeSampler } from './cloud_noise.js';
import { bindEnvironmentMaterial, oncePerFrame, frameObjects } from './stage_haze.js';

const SIZE=12, EARTH=6360000, INTERVAL=.25;
const held=v=>Number.isFinite(v)?Math.max(0,Math.min(1,v)):1;
let installed=false;
// No sampler, no weather-dependent define. Four adjacent cells per vector.
export const CLOUD_SHADOW_GLSL=`
uniform vec4 cloudShadowGrid[36];
// lower x/z, reciprocal full width, enabled
uniform vec4 cloudShadowBounds;
uniform vec3 cloudShadowLight;
float cloudShadowValue;
float cloudShadowCell(ivec2 p) {
  int index=p.y*12+p.x, block=index/4;
  return dot(cloudShadowGrid[block],vec4(equal(ivec4(0,1,2,3),ivec4(index-block*4))));
}
float cloudShadowAt(vec2 world) {
  if(cloudShadowBounds.w<0.5) return 1.0;
  vec2 p=clamp((world-cloudShadowBounds.xy)*cloudShadowBounds.z,0.0,1.0)*11.0;
  ivec2 a=ivec2(floor(p)),b=min(a+ivec2(1),ivec2(11));vec2 f=fract(p);
  float t=mix(mix(cloudShadowCell(a),cloudShadowCell(ivec2(b.x,a.y)),f.x),
    mix(cloudShadowCell(ivec2(a.x,b.y)),cloudShadowCell(b),f.x),f.y);
  return t>=0.0 ? min(t,1.0) : 1.0;
}
float cloudShadowForLight(vec3 direction) {
  vec3 luminary=mat3(viewMatrix)*cloudShadowLight;
  return dot(luminary,direction)>0.99999 ? cloudShadowValue : 1.0;
}
float cloudSpecForLight(vec3 direction, float airVisibility) {
  vec3 luminary=mat3(viewMatrix)*cloudShadowLight;
  return dot(luminary,direction)>0.99999 ? smoothstep(.15,.85,cloudShadowValue)*clamp(airVisibility,0.0,1.0) : 1.0;
}
`;

function installChunks() {
  if(installed)return;installed=true;
  // common is shared by the vertex/fragment stages, including Basic materials
  // that use worldpos_vertex without shadowmap_pars_vertex. They do not sample
  // the grid, and the unused varying is eliminated by the linker.
  THREE.ShaderChunk.common+='\nvarying vec3 vCloudWorld;\n';
  // worldpos_vertex's own worldPosition is conditional on environment/shadows.
  // A separate unconditional position also covers low tier and instanced grass.
  THREE.ShaderChunk.worldpos_vertex+=`
vec4 cloudWorld=vec4(transformed,1.0);
#ifdef USE_BATCHING
cloudWorld=batchingMatrix*cloudWorld;
#endif
#ifdef USE_INSTANCING
cloudWorld=instanceMatrix*cloudWorld;
#endif
vCloudWorld=(modelMatrix*cloudWorld).xyz;`;
  THREE.ShaderChunk.lights_pars_begin=CLOUD_SHADOW_GLSL+THREE.ShaderChunk.lights_pars_begin;
  // Cache outside three's unrolled light loops: the receiver is identical for
  // every directional light. This temporary adds no uniform or sampler.
  THREE.ShaderChunk.lights_fragment_begin='#if NUM_DIR_LIGHTS > 0 || NUM_SUN_LIGHTS > 0\ncloudShadowValue=cloudShadowAt(vCloudWorld.xz);\n#endif\n'+THREE.ShaderChunk.lights_fragment_begin;
  const directCall='RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );';
  const wrappedDirect=`{
  vec3 cloudSpecBefore = reflectedLight.directSpecular;
  #ifdef USE_CLEARCOAT
  vec3 cloudClearcoatBefore = clearcoatSpecularDirect;
  #endif
  ${directCall}
  #if defined( USE_FOG ) && defined( STAGE_HAZE_RING )
  float cloudSpecScale = cloudSpecForLight( directLight.direction, 1.0 - stageRing[4].w );
  #else
  float cloudSpecScale = cloudSpecForLight( directLight.direction, 1.0 );
  #endif
  reflectedLight.directSpecular = mix( cloudSpecBefore, reflectedLight.directSpecular, cloudSpecScale );
  #ifdef USE_CLEARCOAT
  clearcoatSpecularDirect = mix( cloudClearcoatBefore, clearcoatSpecularDirect, cloudSpecScale );
  #endif
  }`;
  for(const anchor of ['getDirectionalLightInfo( directionalLight, directLight );','getSunLightInfo( sunLight, directLight );']) {
    let chunk=THREE.ShaderChunk.lights_fragment_begin;
    const at=chunk.indexOf(anchor);
    if(at<0)throw new Error('Cloud shadow missing r187 light anchor: '+anchor);
    const callAt=chunk.indexOf(directCall,at);
    if(callAt<0)throw new Error('Cloud shadow missing r187 RE_Direct anchor after: '+anchor);
    chunk=chunk.slice(0,callAt)+wrappedDirect+chunk.slice(callAt+directCall.length);
    THREE.ShaderChunk.lights_fragment_begin=chunk.replace(anchor,
      anchor+'\n directLight.color *= cloudShadowForLight(directLight.direction);');
  }
}

function sphere(p,d,radius) {
  const y=p[1]+EARTH,b=p[0]*d[0]+y*d[1]+p[2]*d[2],r=Math.hypot(p[0],y,p[2]);
  const disc=b*b-(r-radius)*(r+radius);
  if(disc<0)return [-1,-1];const root=Math.sqrt(Math.max(0,disc));return [-b-root,-b+root];
}

// Same shell, six quadratic intervals and extinction as CLOUD_GLSL cloudLight.
// density is a test seam; normal calls use the real periodic RGBA8 density.
export function shadowTransmittance(p,direction,options={},density=sampleCloudDensity) {
  if(!(options.coverage>0)||options.type==='none'||options.type===0)return 1;
  const length=Math.hypot(...direction);
  if(!Number.isFinite(length)||length<1e-6)return 1;
  const d=direction.map(v=>v/length);
  // A ground receiver cannot receive direct light through the Earth.
  if(d[1]<0||sphere(p,d,EARTH)[0]>0)return 0;
  const low=['stratus','nimbostratus',3,4].includes(options.type),bottom=low?500:1500,top=low?1500:4000;
  const outer=sphere(p,d,EARTH+top),inner=sphere(p,d,EARTH+bottom);
  const start=Math.max(0,outer[0],inner[1]),end=Math.min(outer[1],250000);
  if(!(end>start))return 1;
  let depth=0;
  for(let j=0;j<6;j++) {
    const a=start+(end-start)*(j/6)**2,b=start+(end-start)*((j+1)/6)**2;
    const sample=p.map((v,i)=>v+d[i]*(a+b)*.5);
    depth+=held(density(sample,options))*(b-a)*.0025;
  }
  return held(Math.exp(-Math.max(0,depth)));
}

// The procedural effects use their own .18 night floor plus a daylight term.
// Replace just the daylight, leaving their HA lamp glow untouched.
function patchEffect(shader) {
  shader.vertexShader='varying vec3 vCloudWorld;\n'+shader.vertexShader.replace(/void main\s*\(\s*\)\s*\{/,
    'void main() { vCloudWorld=(modelMatrix*vec4(position,1.0)).xyz;');
  const main=shader.fragmentShader.search(/void main\s*\(/);
  if(main<0)throw new Error('Cloud shadow effect missing main');
  shader.fragmentShader='varying vec3 vCloudWorld;\n'+CLOUD_SHADOW_GLSL+shader.fragmentShader.slice(0,main)+shader.fragmentShader.slice(main)
    .replace(/\blight\b/g,'cloudEffectLight').replace(/\{/, '{\nfloat cloudEffectLight=.18+max(0.0,light-.18)*cloudShadowAt(vCloudWorld.xz);');
}

export function installCloudShadow(scene,clouds) {
  installChunks();
  // The packed grid IS the uniform: a flat Float32Array goes to uniform4fv as it
  // stands, where 36 Vector4s were flattened again for every lit draw.
  const values=new Float32Array(SIZE*SIZE).fill(1);
  const uniforms={cloudShadowGrid:{value:values},cloudShadowBounds:{value:new THREE.Vector4(-1,-1,.5,0)},
    cloudShadowLight:{value:new THREE.Vector3(0,1,0)}};
  let centre=[0,0],radius=1,sun=[0,1,0],moon=[0,-1,0],last=-Infinity,disposed=false,enabled=true,cpuNoise=null;
  const source=clouds.uniforms;
  function prepare(root) {
    for(const object of frameObjects(root ?? scene,{fresh:root !== undefined})){for(const material of [].concat(object.material||[])) {
      const lit=material.isMeshStandardMaterial||material.isMeshLambertMaterial||material.isMeshPhongMaterial||material.isMeshToonMaterial;
      const effect=material.isShaderMaterial&&material.uniforms?.light;
      if(lit||effect)bindEnvironmentMaterial(material,'cloud-shadow-1',uniforms,effect?patchEffect:null);
    }}
  }
  const previous=scene.onBeforeRender;
  const walk=oncePerFrame(scene,()=>prepare());
  scene.onBeforeRender=function(renderer,...args){previous.call(this,renderer,...args);walk();};
  function sample(x,z) {
    const bounds=uniforms.cloudShadowBounds.value;
    if(bounds.w<.5)return 1;
    const p=[held((x-bounds.x)*bounds.z)*11,held((z-bounds.y)*bounds.z)*11];
    const a=p.map(Math.floor),b=a.map(v=>Math.min(v+1,11)),f=p.map((v,i)=>v-a[i]);
    const at=(x,z)=>values[z*SIZE+x];
    return (at(a[0],a[1])*(1-f[0])+at(b[0],a[1])*f[0])*(1-f[1])+(at(a[0],b[1])*(1-f[0])+at(b[0],b[1])*f[0])*f[1];
  }
  return {uniforms,prepare,sample,centre:()=>sample(...centre),
    set({centre:next,radius:span,sunDir,moonDir,enabled:active}={}) {
      if(next?.every(Number.isFinite))centre=[...next];
      if(Number.isFinite(span)&&span>0)radius=span;
      if(sunDir?.every(Number.isFinite))sun=[...sunDir];
      if(moonDir?.every(Number.isFinite))moon=[...moonDir];
      if(sun[1]>0||moon[1]>0)uniforms.cloudShadowLight.value.fromArray(sun[1]>0?sun:moon).normalize();
      if(active!==undefined)enabled=!!active;
    },
    frame(now) {
      if(disposed||!Number.isFinite(now))return false;
      if(sun[1]>0||moon[1]>0)uniforms.cloudShadowLight.value.fromArray(sun[1]>0?sun:moon).normalize();
      const coverage=source.cloudCoverage.value,type=source.cloudType.value,fade=held(source.cloudFade.value);
      const active=enabled&&coverage>0&&type>.5&&fade>0&&(sun[1]>0||moon[1]>0);
      // Clear/editor/Unlit must stop an old shadow immediately, even between fills.
      uniforms.cloudShadowBounds.value.w=active?1:0;
      if(!active) {values.fill(1);return false;}
      if(now-last<INTERVAL)return false;
      last=now;
      const dir=sun[1]>0?sun:moon;
      uniforms.cloudShadowLight.value.fromArray(dir).normalize();
      const span=radius*3;
      uniforms.cloudShadowBounds.value.set(centre[0]-span/2,centre[1]-span/2,1/span,1);
      // Reuse CPU textures when supplied; GPU noise has no readable image.data.
      cpuNoise ??= clouds.noise?.base.image.data ? clouds.noise : {
        base:createNoiseVolumeSampler(clouds.noise?.base.image.width||128),
        detail:createNoiseVolumeSampler(clouds.noise?.detail.image.width||32,{detail:true})};
      const options={...cpuNoise,coverage,type,offset:source.cloudOffset.value.toArray()};
      for(let z=0;z<SIZE;z++)for(let x=0;x<SIZE;x++) {
        const t=shadowTransmittance([centre[0]-span/2+x*span/11,0,centre[1]-span/2+z*span/11],dir,options);
        values[z*SIZE+x]=1+(t-1)*fade;
      }
      return true;
    },
    dispose(){if(disposed)return;disposed=true;scene.onBeforeRender=previous;cpuNoise=null;},
  };
}
