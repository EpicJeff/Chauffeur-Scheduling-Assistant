import * as THREE from 'three';
import { bindEnvironmentMaterial } from './stage_haze.js';

let installed=false;
const unit=v=>Number.isFinite(v)?Math.max(0,Math.min(1,v)):0;

// xyz: wetness, snow cover (0..8 cm), puddles. w: an 8-bit rain rate in
// the integer part, plus a four-second repeating clock in the fractional part.
// No sampler and exactly one fragment vector, even on the full pool program.
export const WEATHER_GLSL=`
uniform vec4 weatherSurface;
float weatherExposure(float value, float openSky) {
  return value*clamp(openSky,0.0,1.0);
}
float weatherHash(vec2 p) {
  return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);
}
float weatherNoise(vec2 p) {
  vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);
  return mix(mix(weatherHash(i),weatherHash(i+vec2(1.0,0.0)),f.x),
    mix(weatherHash(i+vec2(0.0,1.0)),weatherHash(i+vec2(1.0)),f.x),f.y);
}
float weatherEdge(vec2 p) {
  return weatherNoise(p*.35)*.67+weatherNoise(p*.7+vec2(19.1,7.7))*.33;
}
float weatherWetScale(float luminance, float metal, float wet) {
  float identity=smoothstep(.02,.5,luminance)*mix(1.0,.2,metal);
  return 1.0-.35*wet*identity;
}
float weatherSnow(float up, float cover, float edge) {
  return smoothstep(.55,.85,up)*smoothstep(edge-.12,edge+.12,cover)*smoothstep(0.0,.12,cover);
}
float weatherPuddle(float up, float amount, float edge) {
  return (up>.9?1.0:0.0)*smoothstep(edge-.08,edge+.08,amount)*smoothstep(0.0,.12,amount);
}
float weatherRoughness(float original, float wet, float puddle, float snow) {
  return mix(mix(mix(original,.15,wet),.03,puddle),.7,snow);
}
// Metre cells anchored to the scene, not the camera. Each of nine neighbouring
// .65 m cells emits a ring per second; random offsets keep the grid invisible.
vec2 weatherRipple(vec2 world) {
  float rate=floor(weatherSurface.w)/255.0;
  if(rate<=0.0) return vec2(0.0);
  vec2 cell=floor(world/.65),slope=vec2(0.0);
  float clock=fract(weatherSurface.w)*4.0;
  for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
    vec2 id=cell+vec2(float(x),float(y));
    float seed=weatherHash(id),age=fract(clock+seed);
    vec2 centre=(id+vec2(weatherHash(id+13.7),weatherHash(id+41.3)))*.65;
    vec2 delta=world-centre;float d=length(delta),phase=(d-age*.42)*90.0;
    float band=exp(-abs(d-age*.42)*65.0)*sin(phase);
    float fade=smoothstep(0.0,.08,age)*(1.0-smoothstep(.5,1.0,age));
    float visible=1.0-smoothstep(.5,3.14,fwidth(phase));
    slope+=delta/max(d,.001)*band*fade*visible*rate*.035;
  }
  return slope;
}
`;

const APPLY=`
#ifdef WEATHER_SURFACE_ACTIVE
#ifndef WEATHER_SURFACE_SUBMERGED
if(weatherSurface.x+weatherSurface.y+weatherSurface.z+floor(weatherSurface.w)>0.0) {
  // Use the face normal before maps/ripples: rain cannot turn a pitched face
  // into a puddle, and a normal-map texel cannot collect a speck of snow.
  float weatherUp=inverseTransformDirection(nonPerturbedNormal,viewMatrix).y;
  #ifndef WEATHER_SURFACE_WATER
    float weatherMetal=0.0;
    #ifdef STANDARD
      weatherMetal=metalnessFactor;
    #endif
    float weatherWet=weatherExposure(weatherSurface.x,vWeatherOpen);
    float weatherEdgeValue=(weatherSurface.y>0.0||weatherSurface.z>0.0)?weatherEdge(vWeatherWorld.xz):.5;
    #ifdef WEATHER_SURFACE_ROOF
      float weatherP=0.0;
    #else
      float weatherP=weatherExposure(weatherPuddle(weatherUp,weatherSurface.z,weatherEdgeValue),vWeatherOpen);
    #endif
    float weatherS=weatherExposure(weatherSnow(weatherUp,weatherSurface.y,weatherEdgeValue),vWeatherOpen);
    float weatherLum=dot(diffuseColor.rgb,vec3(.2126,.7152,.0722));
    diffuseColor.rgb *= weatherWetScale(weatherLum,weatherMetal,weatherWet);
    diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.85,.87,.9),weatherS);
    #ifdef STANDARD
      roughnessFactor=weatherRoughness(roughnessFactor,weatherWet,weatherP,weatherS);
      metalnessFactor=mix(metalnessFactor,0.0,weatherS);
    #endif
  #endif
  vec2 weatherSlope=weatherRipple(vWeatherWorld.xz)*smoothstep(.9,.98,weatherUp)*weatherExposure(1.0,vWeatherOpen);
  #ifndef WEATHER_SURFACE_WATER
    weatherSlope*=1.0-weatherS;
  #endif
  vec3 weatherNormal=normal+mat3(viewMatrix)*vec3(weatherSlope.x,0.0,weatherSlope.y);
  normal=weatherNormal/max(length(weatherNormal),.0001);
}
#endif
#endif
`;

function installChunks() {
  if(installed)return;installed=true;
  THREE.ShaderChunk.common+='\nvarying vec3 vWeatherWorld;\nvarying float vWeatherOpen;\n';
  THREE.ShaderChunk.worldpos_vertex+=`
vec4 weatherWorld=vec4(transformed,1.0);
#ifdef USE_BATCHING
weatherWorld=batchingMatrix*weatherWorld;
#endif
#ifdef USE_INSTANCING
weatherWorld=instanceMatrix*weatherWorld;
#endif
vWeatherWorld=(modelMatrix*weatherWorld).xyz;`;
  THREE.ShaderChunk.lights_pars_begin=WEATHER_GLSL+THREE.ShaderChunk.lights_pars_begin;
  THREE.ShaderChunk.normal_fragment_maps+=APPLY;
}

function patchLit(mode) {
  return shader=>{
    shader.vertexShader='attribute float weatherOpen;\n'+shader.vertexShader.replace('#include <worldpos_vertex>',
      '#include <worldpos_vertex>\nvWeatherOpen=weatherOpen;');
    shader.fragmentShader='#define WEATHER_SURFACE_ACTIVE\n'+
      (mode==='water'?'#define WEATHER_SURFACE_WATER\n':mode==='submerged'?'#define WEATHER_SURFACE_SUBMERGED\n':mode==='roof'?'#define WEATHER_SURFACE_ROOF\n':'')+shader.fragmentShader;
  };
}

// Sky-lit custom water effects have no three lighting chunks. They keep their
// authored colour, coverage and lamp glow. Rain bends only their exposed normal;
// vapour has no solid receiving face, so it only carries the shared binding.
function patchEffect(shader) {
  shader.vertexShader='attribute float weatherOpen;\nvarying float vWeatherOpen;\nvarying vec3 vWeatherWorld;\n'+shader.vertexShader.replace(/void main\s*\(\s*\)\s*\{/,
    'void main() { vWeatherOpen=weatherOpen; vWeatherWorld=(modelMatrix*vec4(position,1.0)).xyz;');
  shader.fragmentShader='varying float vWeatherOpen;\nvarying vec3 vWeatherWorld;\n'+WEATHER_GLSL+shader.fragmentShader;
  if(!shader.fragmentShader.includes('varying vec3 vNormal;'))return;
  shader.fragmentShader=shader.fragmentShader.replaceAll('normalize(vNormal)',
    '(weatherEffectNormal/max(length(weatherEffectNormal),.0001))');
  shader.fragmentShader=shader.fragmentShader.replace(/void main\s*\(\s*\)\s*\{/,
    `void main() {
vec3 weatherFace=vNormal/max(length(vNormal),.0001);
float weatherUp=(vec4(weatherFace,0.0)*viewMatrix).y;
vec2 weatherSlope=weatherRipple(vWeatherWorld.xz)*smoothstep(.9,.98,weatherUp)*weatherExposure(1.0,vWeatherOpen);
vec3 weatherEffectNormal=vNormal+mat3(viewMatrix)*vec3(weatherSlope.x,0.0,weatherSlope.y);`);
}

export function installWeatherSurface(scene) {
  installChunks();
  const uniforms={weatherSurface:{value:new THREE.Vector4()}};
  const patches={solid:patchLit('solid'),roof:patchLit('roof'),water:patchLit('water'),submerged:patchLit('submerged')};
  let disposed=false;
  function prepare(root=scene) {
    root.traverse(object=>{for(const material of [].concat(object.material||[])) {
      const lit=material.isMeshStandardMaterial||material.isMeshLambertMaterial||material.isMeshPhongMaterial||material.isMeshToonMaterial;
      const effect=material.isShaderMaterial&&material.uniforms?.light;
      if(!lit&&!effect)continue;
      if(!material.defaultAttributeValues?.weatherOpen)material.defaultAttributeValues={...material.defaultAttributeValues,weatherOpen:[1]};
      // A shallow roof can pass the .9 face test (4:12 => .949). Its existing
      // receiving role excludes puddles explicitly, including library finishes.
      const mode=effect?'effect':material.userData.underwater?'submerged':material.userData.waterSurface||material.userData.litWater?'water'
        :material.name==='roof'||material.userData.materialRole==='roof'?'roof':'solid';
      bindEnvironmentMaterial(material,'weather-surface-'+mode+'-1',uniforms,effect?patchEffect:patches[mode]);
    }});
  }
  const previous=scene.onBeforeRender;
  scene.onBeforeRender=function(renderer,...args){previous.call(this,renderer,...args);prepare();};
  return {uniforms,prepare,
    update(weather={},seconds=0) {
      const u=uniforms.weatherSurface.value;
      if(weather.neutral){u.set(0,0,0,0);return;}
      const rate=['rain','mix'].includes(weather.precip)?unit(weather.rate):0;
      // Leave one float32 ULP before the next integer at maximum rate, so
      // uploading a phase just before wrap cannot increment the rain rate.
      const phase=Number.isFinite(seconds)?Math.min(((seconds%4+4)%4)/4,1-1/32768):0;
      u.set(unit(weather.wetness),unit(weather.snow_cm/8),unit(weather.puddles),Math.round(rate*255)+phase);
    },
    dispose(){if(disposed)return;disposed=true;scene.onBeforeRender=previous;},
  };
}
