import * as THREE from 'three';
import { bindEnvironmentMaterial, oncePerFrame, frameObjects } from './stage_haze.js';

let installed=false;
const unit=v=>Number.isFinite(v)?Math.max(0,Math.min(1,v)):0;

const smooth=(a,b,v)=>{const t=unit((v-a)/(b-a));return t*t*(3-2*t);};
const fract=v=>v-Math.floor(v);
const wetHash=(x,y)=>fract(Math.sin(x*127.1+y*311.7)*43758.5453);
function wetNoise(x,y){
  const ix=Math.floor(x),iy=Math.floor(y);let u=fract(x),v=fract(y);u=u*u*(3-2*u);v=v*v*(3-2*v);
  const a=wetHash(ix,iy),b=wetHash(ix+1,iy),c=wetHash(ix,iy+1),d=wetHash(ix+1,iy+1);
  return (a+(b-a)*u)*(1-v)+(c+(d-c)*u)*v;
}
export function standingWaterAt(x,z,up,weather={}) {
  if(weather.neutral||up<=.9)return 0;
  const edge=wetNoise(x*.35,z*.35)*.67+wetNoise(x*.7+19.1,z*.7+7.7)*.33;
  return smooth(edge-.08,edge+.08,unit(weather.puddles)*.72)*smooth(0,.12,unit(weather.puddles))*smooth(.35,.7,unit(weather.wetness));
}

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
#if !defined(WEATHER_SURFACE_WATER)&&!defined(WEATHER_SURFACE_SUBMERGED)
// Lagarde-style material porosity from per-texel metalness and roughness:
// high for rough non-metals (concrete, shingles, wood), near zero for metals
// and smooth non-porous surfaces (glazed tile, painted metal).
float weatherPorosity(float metal, float roughness) {
  return (1.0-clamp(metal,0.0,1.0))*smoothstep(.35,.85,roughness);
}
float weatherDarkenWet(float porosity, float wet) {
  float w=clamp(wet,0.0,1.0);
  float absorb=w/(.72+.28*w);
  return mix(w*.12,absorb,clamp(porosity,0.0,1.0));
}
float weatherWetRoughness(float original, float porosity, float wet) {
  float w=clamp(wet,0.0,1.0);
  float p=clamp(porosity,0.0,1.0);
  float film=original<.08?original:.08;
  float porousTarget=original<.42?original:mix(.42,original*.52,.5);
  float target=mix(film,porousTarget,p);
  float ramp=mix(smoothstep(0.0,.65,w),w*(.3+.7*w),p);
  return mix(original,target,ramp);
}
// Continuous dielectric water-film coverage: forms directly with wetness on
// non-porous surfaces (and puddles), and only after saturation on porous ones.
float weatherWaterFilm(float porosity, float wet, float puddle) {
  float w=clamp(wet,0.0,1.0);
  float p=clamp(porosity,0.0,1.0);
  float porousFilm=smoothstep(.65,1.0,w)*.35;
  float film=mix(smoothstep(0.0,.75,w),porousFilm,p);
  return max(film,clamp(puddle,0.0,1.0));
}
#endif
float weatherSpot(float wet, float seed, float shape) {
  return smoothstep(seed*.35,seed*.35+.02,wet)*shape;
}
float weatherFilm(float wet) {
  return smoothstep(.35,.7,wet);
}
float weatherGloss(float wet, float spot) {
  // One coverage for absorption and gloss. The broad, gradual film darkens
  // between arrivals and keeps darkening while puddle reflections strengthen.
  return mix(spot*.5,1.0,wet);
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
// Polynomial vector hash: no transcendentals for drops or ripple arrivals.
vec3 weatherRingHash(vec2 p) {
  vec3 q=fract(vec3(p.x,p.y,p.x)*vec3(.1031,.1030,.0973));
  q+=dot(q,q.yxz+33.33);
  return fract((q.xxy+q.yzz)*q.zyx);
}
float weatherDropRadius(float seed) {
  // Metres: 97% are 2.5-7.5 mm; a few coalesced stains reach 10.5 mm.
  return .0025+.005*seed*seed*seed+.003*step(.97,seed);
}
float weatherDropDensity(float up) {
  return mix(.18,.8,smoothstep(.3,.8,abs(up)));
}
float weatherDropTone(float wet, float arrival, float seed) {
  // Fresh stains are darker, then relax into the general film. This also
  // removes all resolved dots before full saturation, without extra noise.
  return mix(.35,1.0,seed)*max(.3,1.0-4.0*max(0.0,wet-arrival*.35-.02))*(1.0-smoothstep(.3,.7,wet));
}
vec4 weatherDropCell(vec2 id, float cellSize, float up) {
  vec3 random=weatherRingHash(id);
  float radius=weatherDropRadius(random.z)/cellSize;
  vec2 centre=vec2(radius)+random.xy*(1.0-2.0*radius);
  float arrival=fract(random.x*13.71+random.y*7.17);
  return vec4(centre,radius,fract(random.y*19.19)>weatherDropDensity(up)?2.0:arrival);
}
float weatherDropLayer(vec2 world, float wet, vec2 dx, vec2 dy, float cellSize, float up) {
  vec2 p=world/cellSize,id=floor(p);
  vec4 spot=weatherDropCell(id,cellSize,up);
  float radius=spot.z;
  vec2 local=fract(p)-spot.xy;
  float d=length(local);vec2 direction=local/max(d,.001);
  float aa=max((abs(dot(direction,dx))+abs(dot(direction,dy)))/cellSize,.001);
  // A soft physical edge survives close inspection; derivatives integrate
  // unresolved stains to their area rather than aliasing into hard dots.
  float edge=max(aa,radius*.3);
  float disc=1.0-smoothstep(radius-edge,radius+edge,d);
  float footprint=max(abs(dx.x)+abs(dy.x),abs(dx.y)+abs(dy.y))/cellSize;
  disc=mix(disc,3.14159*radius*radius,smoothstep(.25,1.0,footprint));
  float tone=weatherDropTone(wet,spot.w,spot.w);
  return spot.w>1.0?0.0:weatherSpot(wet,spot.w,disc)*tone;
}
// Two bounded, incommensurate layers, no neighbour stencil or new texture.
float weatherDrops(vec2 world, float wet, vec2 dx, vec2 dy, float up) {
  // The face projection's second axis is world Y. Compress its coordinates
  // to stretch stains downwards, while preserving derivative filtering.
  float vertical=1.0-smoothstep(.3,.8,abs(up));
  vec2 stretch=vec2(1.0,1.0-.35*vertical);
  world*=stretch;dx*=stretch;dy*=stretch;
  mat2 rotation=mat2(.8,.6,-.6,.8);
  float a=weatherDropLayer(world,wet,dx,dy,.031,up);
  float b=weatherDropLayer(rotation*world+vec2(1.731,4.913),wet,rotation*dx,rotation*dy,.047,up);
  return a+b-a*b;
}
#ifdef WEATHER_SURFACE_ROOF
// Roof wet rivulets and raised beads (ALU only, zero new uniforms/samplers).
// Rivulets use metric (across-slope, downhill-slope); beads use world XZ.
vec3 weatherRoofRivulets(vec2 uv, float wet, float rate, float phase, vec2 dx, vec2 dy) {
  float wetScale=clamp(wet*5.5556,0.0,1.0);
  float density=.78*smoothstep(.08,.65,wet);
  // True Euclidean pixel width across slope (rotation-invariant); fade is for
  // overview distance (~2.1-5.5 cm/px), keeping full contrast at ~1-1.8 cm/px.
  float pxAcross=length(vec2(dx.x,dy.x));
  float vis=1.0-smoothstep(.85,2.2,pxAcross*40.0);
  float avgCov=density*(.05/.44)*.48*wetScale;
  if(vis<=.001) return vec3(0.0,0.0,avgCov);
  float cellX=uv.x*(1.0/.44),id=floor(cellX),localX=fract(cellX);
  vec3 h=weatherRingHash(vec2(id,11.7));
  if(fract(h.z*7.13+h.x*3.17)>=density) return vec3(0.0,0.0,mix(avgCov,0.0,vis));
  // Nearly straight downhill tracks: gentle <=1.2 cm lateral drift over 6-11 m;
  // cos(p1) shares the same sincos for gentle along-track swell.
  float p1=uv.y*(.55+h.y*.45)+h.z*6.2831853;
  float centre=.18+h.x*.64+sin(p1)*(.012/.44);
  float swell=.5+.5*cos(p1);
  float activeFlow=clamp(rate*2.857,0.0,1.0);
  float surgePhi=6.2831853*(uv.y*mix(.56,.87,h.y)-2.0*phase+h.z);
  float surge=.5+.5*sin(surgePhi);
  float fullness=clamp(mix(.54,1.0,swell)*mix(.78,.52+.72*surge*surge,activeFlow),0.0,1.0);
  float invHalfW=mix(55.5556,31.25,h.y)*mix(1.2195,.8929,fullness);
  float s=(localX-centre)*.44*invHalfW;
  float aa=max(pxAcross*invHalfW*.82,.22);
  float mask=clamp((1.0-abs(s))/(2.0*aa)+.5,0.0,1.0);
  float cs=clamp(s,-1.0,1.0),crown=1.0-cs*cs;
  float strength=mask*vis*wetScale;
  return vec3(cs*crown*.55*strength,-cos(surgePhi)*.20*activeFlow*crown*strength,mix(avgCov,mask*fullness*wetScale,vis));
}
vec3 weatherRoofBeads(vec2 uv, float wet, vec2 dx, vec2 dy, float up) {
  vec2 p=uv*29.4118,id=floor(p);
  float footprint=sqrt(max(dot(dx,dx),dot(dy,dy)))*29.4118;
  float vis=1.0-smoothstep(.45,1.15,footprint*3.0909);
  float dens=weatherDropDensity(up);
  float avgCov=dens*.0822*clamp(wet*2.7027,0.0,1.0);
  if(vis<=.001) return vec3(0.0,0.0,avgCov);
  vec3 h=weatherRingHash(id);
  if(fract(h.y*19.19)>dens) return vec3(0.0,0.0,mix(avgCov,0.0,vis));
  float arrived=step(fract(h.x*13.71+h.y*7.17)*.35+.0001,wet);
  float radius=.092+.185*h.z*h.z;
  vec2 centre=vec2(radius)+h.xy*(1.0-2.0*radius);
  vec2 q=(fract(p)-centre)/radius;
  float r2=dot(q,q);
  float disc=clamp((1.25-r2)*1.67,0.0,1.0)*arrived;
  float dome=max(0.0,1.0-r2);
  return vec3(q*(dome*.78*disc*vis),mix(avgCov,disc,vis));
}
#endif
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
  // Water has the same impact slope and wavelength on a puddle or the pool.
  // The former .35 scale cut ring area to 12% and tripled the AA footprint,
  // suppressing puddle rings even when their normal amplitude matched.
  float ringScale=1.0;
  #ifdef WEATHER_SURFACE_POOL
    clock=waterTime;
  #endif
  // Give FXC a runtime trip count instead of nine explicit impact bodies.
  // The four-cell stencil visits the same middle cells in y/x order.
  int impacts=int(count);
  for(int impact=0;impact<impacts;impact++) {
    int width=count==4.0?2:3;
    int y=impact/width,x=impact-y*width;
    vec2 id=count==4.0?midCell+vec2(float(x),float(y)):cell+vec2(float(x-1),float(y-1));
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
    #ifdef WEATHER_SURFACE_ROOF
      float weatherDrop=0.0;
    #else
    float weatherDrop=weatherSurface.x>0.0&&weatherSurface.x<.9?weatherDrops(weatherPlane,weatherSurface.x,weatherDx,weatherDy,weatherUp):0.0;
    #endif
    #ifdef WEATHER_SURFACE_LAWN
      weatherDrop=0.0;
    #endif
    float weatherFilmValue=weatherFilm(weatherSurface.x);
    float weatherBaseRough=.85;
    #ifdef STANDARD
      weatherBaseRough=roughnessFactor;
    #endif
    float weatherPorosityValue=weatherPorosity(weatherMetal,weatherBaseRough);
    weatherWet=weatherExposure(weatherGloss(weatherSurface.x,weatherDrop),vWeatherOpen);
    float weatherGlossValue=weatherWet;
    #ifdef WEATHER_SURFACE_ROOF
      float roofSlopeSin=length(weatherFace.xz);
      float roofUpMask=smoothstep(.05,.25,weatherUp);
      float roofSlopeMask=smoothstep(.02,.12,roofSlopeSin)*roofUpMask;
      vec3 roofAcrossDir=vec3(0.0,0.0,-1.0);
      vec3 roofDownDir=vec3(1.0,0.0,0.0);
      vec2 roofNoiseUv=vWeatherWorld.xz*.8;
      float roofWetRaw=weatherWet*roofUpMask;
      float roofImpervious=1.0-weatherPorosityValue;
      // Impervious roofs (metal, smooth tile) form rivulets and beads; porous
      // roofs (asphalt/wood shingles) absorb water so beads soak in and rivulets stay faint.
      float roofRivWeight=mix(.12,1.0,roofImpervious*roofImpervious);
      float roofBeadWeight=clamp(roofImpervious*2.0-.5,0.0,1.0);
      vec3 roofRiv=vec3(0.0);
      if(roofSlopeMask>0.0){
        vec2 roofHoriz=weatherFace.xz/roofSlopeSin;
        roofAcrossDir=vec3(roofHoriz.y,0.0,-roofHoriz.x);
        roofDownDir=vec3(roofHoriz.x*weatherUp,-roofSlopeSin,roofHoriz.y*weatherUp);
        vec2 roofUv=vec2(dot(vWeatherWorld,roofAcrossDir),dot(vWeatherWorld,roofDownDir));
        roofNoiseUv=mix(roofNoiseUv,vec2(roofUv.x*2.2,roofUv.y*.3),roofSlopeMask);
        if(roofWetRaw>0.0){
          vec2 roofDx=vec2(dot(weatherWorldDx,roofAcrossDir),dot(weatherWorldDx,roofDownDir));
          vec2 roofDy=vec2(dot(weatherWorldDy,roofAcrossDir),dot(weatherWorldDy,roofDownDir));
          float roofRate=floor(weatherSurface.w)/255.0;
          float roofPhase=roofRate>0.0?fract(weatherSurface.w):0.0;
          roofRiv=weatherRoofRivulets(roofUv,roofWetRaw,roofRate,roofPhase,roofDx,roofDy)*(roofSlopeMask*roofRivWeight);
        }
      }
      vec3 roofBead=vec3(0.0);
      if(roofWetRaw>0.0&&roofBeadWeight>0.0){
        roofBead=weatherRoofBeads(vWeatherWorld.xz,roofWetRaw,weatherWorldDx.xz,weatherWorldDy.xz,weatherUp)*roofBeadWeight;
      }
      float roofBeadKeep=1.0-roofRiv.z;
      float roofWaterCov=clamp(roofRiv.z+roofBead.z*roofBeadKeep,0.0,1.0);
      weatherGlossValue=1.0;
      weatherGlossValue*=mix(.65,1.0,weatherNoise(roofNoiseUv));
      float roofFilmVar=(weatherGlossValue-.65)*(1.0/.35);
    #else
      if(abs(weatherUp)<.5)weatherGlossValue*=mix(.45,1.0,weatherNoise(weatherPlane*vec2(12.0,.7)));
    #endif
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
    diffuseColor.rgb *= weatherWetScale(weatherLum,weatherMetal,weatherDarkenWet(weatherPorosityValue,weatherWet));
    diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.85,.87,.9),weatherS);
    #ifdef STANDARD
      #ifdef WEATHER_SURFACE_LAWN
        roughnessFactor=weatherRoughness(mix(roughnessFactor,.42,weatherGlossValue),0.0,weatherP,weatherS);
      #elif defined(WEATHER_SURFACE_ROOF)
        float roofBaseWet=weatherWetRoughness(roughnessFactor,weatherPorosityValue,roofWetRaw);
        float roofTarget=mix(min(roofBaseWet,mix(.14,.08,roofFilmVar)),clamp(roofBaseWet*mix(.82,1.12,roofFilmVar),.045,1.0),weatherPorosityValue);
        float roofRough=mix(roofBaseWet,roofTarget,roofWetRaw);
        roofRough=mix(roofRough,min(roofRough,.045),roofWaterCov*roofWetRaw);
        roughnessFactor=mix(roofRough,.7,weatherS);
      #else
        roughnessFactor=weatherRoughness(weatherWetRoughness(roughnessFactor,weatherPorosityValue,weatherGlossValue),0.0,weatherP,weatherS);
      #endif
      // Clear dielectric water film shifts dark/painted metals toward untinted
      // water F0 while leaving bright bare metals (galvanized, fire-pit, chrome)
      // metallic so they do not turn into light-grey diffuse plastic when wet.
      float weatherWaterFilmCov=weatherWaterFilm(weatherPorosityValue,weatherWet,weatherP);
      #ifdef WEATHER_SURFACE_ROOF
        weatherWaterFilmCov=max(weatherWaterFilmCov,roofWaterCov*roofWetRaw);
      #endif
      metalnessFactor=mix(metalnessFactor,0.0,max(weatherWaterFilmCov*(1.0-smoothstep(.06,.20,weatherLum*weatherMetal)),weatherS));
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
  #ifdef WEATHER_SURFACE_ROOF
    vec3 weatherNormal=normal+mat3(viewMatrix)*((roofAcrossDir*roofRiv.x+roofDownDir*roofRiv.y+vec3(roofBead.x,0.0,roofBead.y)*roofBeadKeep)*(1.0-weatherS));
  #else
  vec3 weatherNormal=normal+mat3(viewMatrix)*vec3(weatherSlope.x,0.0,weatherSlope.y);
  #endif
  normal=weatherNormal/max(length(weatherNormal),.0001);
  #if !defined(WEATHER_SURFACE_WATER)&&!defined(WEATHER_SURFACE_ROOF)
    vec3 weatherReflected=inverseTransformDirection(reflect(normalize(vViewPosition),normal),viewMatrix);
    // Wet surroundings occlude the grazing sky. Keep attenuating with the
    // shared coverage after the horizon mask fills, so late Fresnel gains
    // cannot outrun absorption on partially exposed ground.
    weatherHorizonDamp=weatherHorizon(weatherReflected.y,smoothstep(0.0,.35,max(weatherGlossValue,weatherP))*(1.0-weatherS))*(1.0-.25*weatherWet*(1.0-weatherS));
  #elif defined(WEATHER_SURFACE_ROOF)
    vec3 roofViewDir=normalize(vViewPosition);
    vec3 roofReflected=inverseTransformDirection(reflect(-roofViewDir,normal),viewMatrix);
    float roofWetNoSnow=roofWetRaw*(1.0-weatherS);
    // Horizon damp only where the reflected ray points at or below the horizon;
    // dark impervious wet roofs catch the overcast sky with straight wet streaks,
    // while light roofs and porous shingles keep an unboosted sheen.
    float roofHorizon=weatherHorizon(roofReflected.y,roofWetNoSnow);
    float roofNoV=clamp(dot(normal,roofViewDir),0.0,1.0);
    float roofGrazing=(1.0-roofNoV)*(1.0-roofNoV);
    float roofSkyGrad=smoothstep(.15,.95,roofReflected.y);
    float roofCoatWeight=(1.0-smoothstep(.1,.4,weatherLum))*roofImpervious;
    float roofFilmSheen=mix(1.50,2.25,clamp(roofGrazing*.75+roofSkyGrad*.45,0.0,1.0))*mix(.90,1.08,roofFilmVar);
    float roofWaterGlint=roofWaterCov*1.35*(.70+.45*roofSkyGrad);
    float roofSheen=mix(1.0,roofFilmSheen+roofWaterGlint,roofCoatWeight);
    weatherHorizonDamp=mix(1.0,roofHorizon*roofSheen,roofWetNoSnow);
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

function patchLit(mode,instanceExposure=false) {
  return shader=>{
    // Never declare twice, whatever wraps this material (owner console 2026-11-19).
    if(shader.vertexShader.includes('attribute float weatherOpen;'))return;
    shader.vertexShader='attribute float weatherOpen;\n'+shader.vertexShader.replace('#include <worldpos_vertex>',
      '#include <worldpos_vertex>\nvWeatherOpen='+(instanceExposure?'instanceColor.r':'weatherOpen')+';');
    shader.fragmentShader='#define WEATHER_SURFACE_ACTIVE\n'+
      (mode==='water'?'#define WEATHER_SURFACE_WATER\n':mode==='submerged'?'#define WEATHER_SURFACE_SUBMERGED\n':mode==='roof'?'#define WEATHER_SURFACE_ROOF\n':mode==='lawn'?'#define WEATHER_SURFACE_LAWN\n':'')+shader.fragmentShader;
  };
}

// Sky-lit custom water effects have no three lighting chunks. They keep their
// authored colour, coverage and lamp glow. Rain bends only their exposed normal;
// vapour has no solid receiving face, so it only carries the shared binding.
function patchEffect(shader) {
  if(shader.vertexShader.includes('attribute float weatherOpen;'))return;
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
  const patches={solid:patchLit('solid'),lawn:patchLit('lawn'),grass:patchLit('lawn',true),roof:patchLit('roof'),water:patchLit('water'),submerged:patchLit('submerged')};
  let disposed=false;
  function prepare(root) {
    for(const object of frameObjects(root ?? scene,{fresh:root !== undefined})){for(const material of [].concat(object.material||[])) {
      const lit=material.isMeshStandardMaterial||material.isMeshLambertMaterial||material.isMeshPhongMaterial||material.isMeshToonMaterial;
      const effect=material.isShaderMaterial&&material.uniforms?.light;
      if(!lit&&!effect)continue;
      if(!material.defaultAttributeValues?.weatherOpen)material.defaultAttributeValues={...material.defaultAttributeValues,weatherOpen:[1]};
      // A shallow roof can pass the .9 face test (4:12 => .949). Its existing
      // receiving role excludes puddles explicitly, including library finishes.
      const mode=effect?'effect':material.userData.underwater?'submerged':material.userData.waterSurface||material.userData.litWater?'water'
        :material.name==='roof'||material.userData.materialRole==='roof'?'roof'
        :material.userData.seasonLawn||material.userData.materialRole==='lawn'||material.name==='lawn'?'lawn':'solid';
      bindEnvironmentMaterial(material,'weather-surface-'+mode+'-1',uniforms,effect?patchEffect:material.userData.grassUniforms?patches.grass:patches[mode]);
    }}
  }
  const previous=scene.onBeforeRender;
  const walk=oncePerFrame(scene,()=>prepare());
  scene.onBeforeRender=function(renderer,...args){previous.call(this,renderer,...args);walk();};
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
