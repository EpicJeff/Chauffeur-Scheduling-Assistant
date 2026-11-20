import * as THREE from 'three';
import { bindEnvironmentMaterial } from './stage_haze.js';

let installed=false;
const unit=v=>Number.isFinite(v)?Math.max(0,Math.min(1,v)):0;

// xyz: wetness, snow cover (0..8 cm), puddles. w: an 8-bit rain rate in
// the integer part, plus a four-second repeating clock in the fractional part.
// No sampler and exactly one fragment vector, even on the full pool program.
export const WEATHER_GLSL=`
uniform vec4 weatherSurface;
// Per-invocation temporaries, not uniforms. Derivatives are captured before
// receiver branches so covered/uncovered lanes never yield undefined slopes.
vec3 weatherWorldDx,weatherWorldDy;
// Sky reflection kept on wet ground: 1 dry, lower where the reflected ray runs
// toward the horizon (house, trees and fences there, not bright sky).
float weatherHorizonDamp=1.0;
float weatherHorizon(float reflectedUp, float wet) {
  return mix(1.0,mix(.22,1.0,smoothstep(.04,.5,reflectedUp)),clamp(wet,0.0,1.0));
}
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
  float identity=smoothstep(.02,.5,luminance)*mix(1.0,.14,metal);
  return 1.0-.5*wet*identity;
}
float weatherSpot(float wet, float seed, float shape) {
  return smoothstep(seed*.35,seed*.35+.02,wet)*shape;
}
float weatherFilm(float wet) {
  return smoothstep(.35,.7,wet);
}
float weatherGloss(float wet, float spot) {
  return mix(spot*.75,1.0,smoothstep(.35,.9,wet));
}
float weatherLawnPuddle(float amount) {
  return smoothstep(.8,1.0,amount)*.35;
}
float weatherRingStrength(float rate, float seed) {
  return (rate>0.0&&seed<=rate?1.0:0.0)*mix(.07,.22,rate);
}
float weatherRingBand(float d, float age) {
  return exp(-abs(d-age*.46)*28.0)*sin((d-age*.46)*48.0);
}
float weatherRingSupport(float d, float age) {
  return 1.0-smoothstep(.14,.18,abs(d-age*.46));
}
// Three-centimetre impact marks. Integrating unresolved discs avoids glitter
// at distance, while resolved spots keep their own hashed arrival threshold.
float weatherDrops(vec2 world, float wet, vec2 dx, vec2 dy) {
  vec2 p=world/.03,id=floor(p);
  float radius=mix(.26,.42,weatherHash(id+17.3));
  vec2 jitter=(vec2(weatherHash(id+3.1),weatherHash(id+41.7))-.5)*2.0*(.5-radius);
  vec2 local=fract(p)-.5-jitter;
  float d=length(local);vec2 direction=local/max(d,.001);
  float aa=max((abs(dot(direction,dx))+abs(dot(direction,dy)))/.03,.001);
  float disc=1.0-smoothstep(radius-aa,radius+aa,d);
  float footprint=max(abs(dx.x)+abs(dy.x),abs(dx.y)+abs(dy.y))/.03;
  disc=mix(disc,3.14159*radius*radius,smoothstep(.25,1.0,footprint));
  return weatherSpot(wet,weatherHash(id),disc);
}
float weatherSnow(float up, float cover, float edge) {
  return smoothstep(.55,.85,up)*smoothstep(edge-.12,edge+.12,cover)*smoothstep(0.0,.12,cover);
}
float weatherPuddle(float up, float amount, float edge) {
  return (up>.9?1.0:0.0)*smoothstep(edge-.08,edge+.08,amount*.72)*smoothstep(0.0,.12,amount);
}
float weatherRoughness(float original, float wet, float puddle, float snow) {
  return mix(mix(mix(original,.12,wet),.03,puddle),.7,snow);
}
// One impact per .6 m cell, 3 cycles/s: still 8.33 hits/m2/s at pouring.
// A polynomial vector hash supplies arrival and centre together, without the
// old four sine hashes per contribution. Keep the surface/puddle noise intact.
vec3 weatherRingHash(vec2 p) {
  vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));
  q+=dot(q,q.yxz+33.33);
  return fract((q.xxy+q.yzz)*q.zyx);
}
float weatherRingCount(float distanceSq) {
  return distanceSq>=1296.0?0.0:distanceSq>=324.0?4.0:9.0;
}
vec2 weatherRipple(vec2 world) {
  float rate=floor(weatherSurface.w)/255.0;
  if(rate<=0.0) return vec2(0.0);
  vec3 fromEye=vWeatherWorld-cameraPosition;
  float distanceSq=dot(fromEye,fromEye),count=weatherRingCount(distanceSq);
  if(count==0.0) return vec2(0.0);
  vec2 cell=floor(world/.6),slope=vec2(0.0);
  vec2 midCell=floor(world/.6-.5);
  // Evaluate derivatives before divergent per-impact gates, including rate.
  vec2 dx=weatherWorldDx.xz,dy=weatherWorldDy.xz;
  float farFade=1.0-smoothstep(784.0,1296.0,distanceSq);
  float nearFade=1.0-smoothstep(144.0,324.0,distanceSq);
  float clock=fract(weatherSurface.w)*4.0;
  // A puddle's rings are a third the size of the pool's, with a finer wave.
  float ringScale=.35;
  #ifdef WEATHER_SURFACE_WATER
    ringScale=1.0;
  #endif
  #ifdef WEATHER_SURFACE_POOL
    clock=waterTime;
  #endif
  for(int y=-1;y<=1;y++) for(int x=-1;x<=1;x++) {
    vec2 id=cell+vec2(float(x),float(y));
    bool mid=id.x>=midCell.x&&id.x<=midCell.x+1.0&&id.y>=midCell.y&&id.y<=midCell.y+1.0;
    if(count==4.0&&!mid)continue;
    vec3 random=weatherRingHash(id);
    float strength=weatherRingStrength(rate,fract(random.x*7.13));
    if(strength==0.0)continue;
    float age=fract(clock*3.0+random.x);
    vec2 centre=(id+random.yz)*.6;
    vec2 delta=world-centre;float d=length(delta);
    // Outside this annulus the old envelope is below .0065. Fade that tail
    // before the expensive wave, rather than evaluating almost-zero crests.
    float support=weatherRingSupport(d/ringScale,age);
    if(support<=0.0)continue;
    vec2 direction=delta/max(d,.001);
    float footprint=48.0/ringScale*(abs(dot(direction,dx))+abs(dot(direction,dy)));
    float visible=1.0-smoothstep(1.0,3.14,footprint);
    if(visible<=0.0)continue;
    float band=weatherRingBand(d/ringScale,age);
    float fade=smoothstep(0.0,.06,age)*(1.0-smoothstep(.6,1.0,age));
    // One layer instead of two: sqrt(2) retains their combined slope power.
    slope+=direction*band*fade*visible*strength*1.414214*support*farFade*(mid?1.0:nearFade);
  }
  return slope;
}
`;

const APPLY=`
#ifdef WEATHER_SURFACE_ACTIVE
#ifndef WEATHER_SURFACE_SUBMERGED
weatherWorldDx=dFdx(vWeatherWorld);weatherWorldDy=dFdy(vWeatherWorld);
if(vWeatherOpen>0.0&&weatherSurface.x+weatherSurface.y+weatherSurface.z+floor(weatherSurface.w)>0.0) {
  // Use the face normal before maps/ripples: rain cannot turn a pitched face
  // into a puddle, and a normal-map texel cannot collect a speck of snow.
  vec3 weatherFace=inverseTransformDirection(nonPerturbedNormal,viewMatrix);
  float weatherUp=weatherFace.y;
  #ifndef WEATHER_SURFACE_WATER
    float weatherMetal=0.0;
    #ifdef STANDARD
      weatherMetal=metalnessFactor;
    #endif
    float weatherWet=weatherExposure(weatherSurface.x,vWeatherOpen);
    vec2 weatherPlane=abs(weatherUp)>.5?vWeatherWorld.xz:(abs(weatherFace.x)>abs(weatherFace.z)?vWeatherWorld.zy:vWeatherWorld.xy);
    vec2 weatherDx=abs(weatherUp)>.5?weatherWorldDx.xz:(abs(weatherFace.x)>abs(weatherFace.z)?weatherWorldDx.zy:weatherWorldDx.xy);
    vec2 weatherDy=abs(weatherUp)>.5?weatherWorldDy.xz:(abs(weatherFace.x)>abs(weatherFace.z)?weatherWorldDy.zy:weatherWorldDy.xy);
    float weatherDrop=weatherSurface.x>0.0&&weatherSurface.x<.9?weatherDrops(weatherPlane,weatherSurface.x,weatherDx,weatherDy):0.0;
    #ifdef WEATHER_SURFACE_LAWN
      weatherDrop=0.0;
    #endif
    float weatherFilmValue=weatherFilm(weatherSurface.x);
    float weatherGlossValue=weatherExposure(weatherGloss(weatherSurface.x,weatherDrop),vWeatherOpen);
    #ifdef WEATHER_SURFACE_ROOF
      weatherGlossValue*=mix(.65,1.0,weatherNoise(weatherPlane*vec2(12.0,.7)));
    #else
      if(abs(weatherUp)<.5)weatherGlossValue*=mix(.45,1.0,weatherNoise(weatherPlane*vec2(12.0,.7)));
    #endif
    weatherWet=weatherExposure(weatherFilmValue,vWeatherOpen);
    bool weatherNeedsEdge=weatherSurface.y>0.0&&weatherUp>.55;
    #ifndef WEATHER_SURFACE_ROOF
      weatherNeedsEdge=weatherNeedsEdge||(weatherSurface.z>0.0&&weatherUp>.9&&weatherFilmValue>0.0);
    #endif
    float weatherEdgeValue=weatherNeedsEdge?weatherEdge(vWeatherWorld.xz):.5;
    #ifdef WEATHER_SURFACE_ROOF
      float weatherP=0.0;
    #else
      float weatherP=weatherExposure(weatherPuddle(weatherUp,weatherSurface.z,weatherEdgeValue),vWeatherOpen);
    #endif
    weatherP*=weatherFilmValue;
    #ifdef WEATHER_SURFACE_LAWN
      weatherP*=weatherLawnPuddle(weatherSurface.z);
    #endif
    float weatherS=weatherExposure(weatherSnow(weatherUp,weatherSurface.y,weatherEdgeValue),vWeatherOpen);
    float weatherLum=dot(diffuseColor.rgb,vec3(.2126,.7152,.0722));
    #ifdef WEATHER_SURFACE_LAWN
      weatherLum=max(weatherLum,.35);
    #endif
    diffuseColor.rgb *= weatherWetScale(weatherLum,weatherMetal,weatherWet)-weatherExposure(.25*weatherDrop*(1.0-weatherFilmValue),vWeatherOpen);
    diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.85,.87,.9),weatherS);
    #ifdef STANDARD
      #ifdef WEATHER_SURFACE_LAWN
        roughnessFactor=weatherRoughness(mix(roughnessFactor,.42,weatherGlossValue),0.0,weatherP,weatherS);
      #else
        roughnessFactor=weatherRoughness(roughnessFactor,weatherGlossValue,weatherP,weatherS);
      #endif
      metalnessFactor=mix(metalnessFactor,0.0,weatherS);
    #endif
  #endif
  float weatherRingWeight=smoothstep(.9,.98,weatherUp)*weatherExposure(1.0,vWeatherOpen);
  #ifndef WEATHER_SURFACE_WATER
    weatherRingWeight*=1.0-weatherS;
    // Rings form on standing water only: puddles here, the pool in its own mode.
    weatherRingWeight*=weatherP;
  #endif
  vec2 weatherSlope=vec2(0.0);
  if(weatherRingWeight>0.0)weatherSlope=weatherRipple(vWeatherWorld.xz)*weatherRingWeight;
  vec3 weatherNormal=normal+mat3(viewMatrix)*vec3(weatherSlope.x,0.0,weatherSlope.y);
  normal=weatherNormal/max(length(weatherNormal),.0001);
  #if !defined(WEATHER_SURFACE_WATER)&&!defined(WEATHER_SURFACE_ROOF)
    vec3 weatherReflected=inverseTransformDirection(reflect(normalize(vViewPosition),normal),viewMatrix);
    // Any wet gloss already strengthens grazing reflection; damp it fully from a third on.
    weatherHorizonDamp=weatherHorizon(weatherReflected.y,smoothstep(0.0,.35,max(weatherGlossValue,weatherP))*(1.0-weatherS));
  #endif
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
  THREE.ShaderChunk.lights_fragment_maps+='\n#if defined(RE_IndirectSpecular)&&defined(WEATHER_SURFACE_ACTIVE)\nradiance*=weatherHorizonDamp;\n#endif\n';
}

function patchLit(mode) {
  return shader=>{
    shader.vertexShader='attribute float weatherOpen;\n'+shader.vertexShader.replace('#include <worldpos_vertex>',
      '#include <worldpos_vertex>\nvWeatherOpen=weatherOpen;');
    shader.fragmentShader='#define WEATHER_SURFACE_ACTIVE\n'+
      (mode==='water'?'#define WEATHER_SURFACE_WATER\n':mode==='submerged'?'#define WEATHER_SURFACE_SUBMERGED\n':mode==='roof'?'#define WEATHER_SURFACE_ROOF\n':mode==='lawn'?'#define WEATHER_SURFACE_LAWN\n':'')+shader.fragmentShader;
  };
}

// Sky-lit custom water effects have no three lighting chunks. They keep their
// authored colour, coverage and lamp glow. Rain bends only their exposed normal;
// vapour has no solid receiving face, so it only carries the shared binding.
function patchEffect(shader) {
  shader.vertexShader='attribute float weatherOpen;\nvarying float vWeatherOpen;\nvarying vec3 vWeatherWorld;\n'+shader.vertexShader.replace(/void main\s*\(\s*\)\s*\{/,
    'void main() { vWeatherOpen=weatherOpen; vWeatherWorld=(modelMatrix*vec4(position,1.0)).xyz;');
  shader.fragmentShader='#define WEATHER_SURFACE_WATER\nvarying float vWeatherOpen;\nvarying vec3 vWeatherWorld;\n'+WEATHER_GLSL+shader.fragmentShader;
  if(!shader.fragmentShader.includes('varying vec3 vNormal;'))return;
  shader.fragmentShader=shader.fragmentShader.replaceAll('normalize(vNormal)',
    '(weatherEffectNormal/max(length(weatherEffectNormal),.0001))');
  shader.fragmentShader=shader.fragmentShader.replace(/void main\s*\(\s*\)\s*\{/,
    `void main() {
weatherWorldDx=dFdx(vWeatherWorld);weatherWorldDy=dFdy(vWeatherWorld);
vec3 weatherFace=vNormal/max(length(vNormal),.0001);
float weatherUp=(vec4(weatherFace,0.0)*viewMatrix).y;
vec2 weatherSlope=vec2(0.0);
if(vWeatherOpen>0.0&&weatherUp>.9)weatherSlope=weatherRipple(vWeatherWorld.xz)*smoothstep(.9,.98,weatherUp)*weatherExposure(1.0,vWeatherOpen);
vec3 weatherEffectNormal=vNormal+mat3(viewMatrix)*vec3(weatherSlope.x,0.0,weatherSlope.y);`);
}

export function installWeatherSurface(scene) {
  installChunks();
  const uniforms={weatherSurface:{value:new THREE.Vector4()}};
  const patches={solid:patchLit('solid'),lawn:patchLit('lawn'),roof:patchLit('roof'),water:patchLit('water'),submerged:patchLit('submerged')};
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
        :material.name==='roof'||material.userData.materialRole==='roof'?'roof'
        :material.userData.seasonLawn||material.userData.materialRole==='lawn'||material.name==='lawn'?'lawn':'solid';
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
