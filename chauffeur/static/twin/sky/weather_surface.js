import * as THREE from 'three';
import { bindEnvironmentMaterial, oncePerFrame, frameObjects } from './stage_haze.js';
import { createRoofWater } from './roof_water.js';

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
// the integer part, plus a 64-second repeating clock in the fractional part
// (multiple of 4 s so 3 Hz puddle/pool ripples are unchanged).
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
// Roof-only packed state: x = roof wetness (0..1), y = runoff flow (0..1),
// z = moving water film strength (0..1), w = damp-trail retention (0..1).
uniform vec4 weatherRoof;
// Roof water: growing pools/beads, scattered release-event winding rivulets
// with finite head/tail and lens normals, and a moving micro-ripple water film.
// ALU only, zero new samplers/varyings/attributes.
vec3 weatherRoofRivulets(vec2 uv, float wet, float flow, float phase, float vis, float trail) {
  vec2 wr=min(vec2(wet,flow)*vec2(1.8,2.2),1.0);
  float isFlow=flow>0.0?1.0:0.0;
  float activeProb=wr.x*(flow>0.0?min(wr.y,.95):.35);
  float avgCov=activeProb*.08*trail;
  if(vis<=.001) return vec3(0.0,0.0,avgCov);
  float baseRow=floor(uv.y*.416667),lenScale=.85+.55*wr.y,cov=0.0;
  vec2 slope=vec2(0.0,0.0);
  // Two golden-ratio staggered rows cover 2.4 m of unclipped downhill travel with no lattice.
  int rows=flow>0.0?2:1;
  for(int k=0;k<rows;k++) {
    float row=baseRow-float(k);
    float cellX=uv.x*3.333333+fract(row*.381966);
    vec3 h=weatherRingHash(vec2(floor(cellX),row));
    float dyM=uv.y-(row+.03+.94*h.y)*2.4;
    if(fract(h.z*9.37)<activeProb) {
      float dxM=(fract(cellX)-(.24+.52*h.x))*.30;
      float hz6=h.z*6.0,h2=fract(hz6);
      // Smooth per-stream random winding path (zero at pool dyM=0, two random polynomial waves).
      vec2 wp=fract(max(0.0,dyM)*vec2(.50+.50*h.x,1.10+.90*h.y))-.5;
      float rx=dxM-dot(wp*(.5-abs(wp)),h.xy*vec2(1.15,.65)-vec2(.575,.325));
      // Seamless per-stream release cycle over the 64 s clock (integer 5..10 cycles).
      float tau=fract(phase*(5.0+floor(hz6))+h2);
      float runT=clamp((tau-.22)*1.28205,0.0,1.0);
      float headY=runT*2.35;
      // Tail stays at the pool until water is spent, then travels downhill.
      float tailY=flow>0.0?max(0.0,headY-(.75+.95*h2)*lenScale):(.65+1.10*h2);
      float lifeFade=clamp(5.5-runT*5.5,0.0,1.0)*isFlow;
      // Unified origin pool -> bulbous leading head bead (grows at dyM=0, then launches).
      float beadAmp=min(tau*4.5455,lifeFade);
      vec2 hd=vec2(rx,dyM-headY)*32.0;
      float hDome=max(0.0,beadAmp-dot(hd,hd));
      // Longitudinal masks: tail taper, head cap, damp trail start & downhill fade.
      vec4 seg=clamp(vec4(dyM-tailY,headY-dyM,dyM,dyM-tailY+1.54)*vec4(4.5,22.0,12.5,.65),0.0,1.0);
      float s=rx*44.0,crown=max(0.0,1.0-s*s),bodyMask=seg.x*seg.y*lifeFade;
      float lensN=s*crown*2.8*bodyMask;
      float trailMask=seg.z*(1.0-seg.x)*seg.w*(.42*trail);
      cov=max(cov,max(clamp(crown*2.4,0.0,1.0)*max(bodyMask,trailMask),hDome*2.6));
      slope+=vec2(lensN,0.0)+hd*(hDome*2.1);
    }
  }
  return vec3(slope*(vis*wr.x),mix(avgCov,min(cov,1.0)*wr.x,vis));
}
// Analytic gradient of C0-continuous polynomial 2D value noise (zero transcendentals).
vec2 weatherRoofGrad(vec2 p) {
  vec2 i=floor(p),f=fract(p);
  vec2 du=f*(1.0-f);
  vec4 x=fract(i.x*.1031+vec4(0.0,.1031,0.0,.1031));
  vec4 y=fract(i.y*.1030+vec4(0.0,0.0,.1030,.1030));
  vec4 q=x*19.3+(y*31.7+11.1);
  vec4 h=fract(q*q);
  return du*vec2(mix(h.y-h.x,h.w-h.z,f.y),mix(h.z-h.x,h.w-h.y,f.x));
}
// Moving thin water film: metre-scale lane variation, three overlapping micro-ripple
// layers (~3.8, 2.1, 1.5 cm) with two-phase downhill flow cross-fade, and tiny
// advected drop-impact rings. Integer cycles per 64 s guarantee seamless wrap.
vec2 weatherRoofFilm(vec2 uv, float film, float rate, float phase, float px) {
  if(film<=.001) return vec2(0.0);
  // Slow metre-scale variation across the roof modulates lane speed and strength.
  vec3 lw=abs(fract(uv.x*vec3(.53,-.37,.29)+uv.y*vec3(.19,.27,-.17)-phase*vec3(2.0,3.0,1.0))*2.0-1.0);
  float lane=dot(lw,vec3(.45,.35,.20));
  // x: flow speed scale, y: ring drift scale (0.80*x), zw: across/down amplitude.
  vec4 lm=vec4(.72,.57,.53,.69)+lane*vec4(.56,.44,.77,1.01);
  vec2 slope=vec2(0.0);
  int steps=film>.001?6:0;
  for(int k=0;k<steps;k++) {
    float fk=float(k),lay=floor(fk*.5);
    vec4 par=vec4(26.0,48.0,.56,.52)+lay*vec4(21.0,32.0,-.10,-.14);
    float vis=clamp(2.0-2.0*px*par.x,0.0,1.0);
    float ph=fract(phase*par.y+fk*.5);
    float w=(1.0-abs(2.0*ph-1.0))*par.w*vis;
    float sk=.35-lay*.53,ay=uv.y-ph*par.z*lm.x;
    vec2 g=weatherRoofGrad(vec2(uv.x+ay*sk,ay)*par.x+vec2(fk*13.7,fk*29.3));
    slope+=vec2(g.x,g.y+g.x*sk)*w;
  }
  // Sparse tiny drop-impact rings feed in while raining and drift downhill with the flow.
  float ringW=clamp(2.0-px*95.0,0.0,1.0)*(rate*-5.5);
  vec2 ip=vec2(uv.x+uv.y*.43,uv.y)*11.76;
  float rq=dot(fract(floor(ip)*vec2(.1031,.1030)),vec2(19.3,31.7));
  vec2 rh=fract(rq*(rq+vec2(11.1,28.4)));
  float age=fract(phase*128.0+rh.y);
  vec2 d=fract(ip)-vec2(.26+.48*rh.x,.16+.26*rh.y+age*lm.y);
  float s=dot(d,d)*52.0-.10-age*6.8;
  vec2 re=max(vec2(0.0),vec2(1.0-s*s,1.0-age*2.5));
  slope+=d*(s*re.x*re.y*ringW);
  return slope*(lm.zw*film);
}
vec3 weatherRoofBeads(vec2 uv, float wet, float flow, float phase, float vis, float keep) {
  // Varied coalesced beads (6.8 cm row-staggered cells, ~1 to 4.9 cm diameter)
  // that grow with wetness and flow, thin and shrink as the roof dries, and
  // freeze when flow reaches 0.
  float avgCov=.085*wet*keep;
  vec2 p=uv*14.7059;
  p.x+=floor(p.y)*.381966;
  vec3 h=weatherRingHash(floor(p));
  float thin=clamp(wet*8.0-h.x*6.8,0.0,1.0);
  float mask=(h.y<=.72?keep:0.0)*thin;
  float growth=clamp(wet*(.4+flow+fract(phase*4.0+h.x)),0.0,1.0);
  float radius=(.092+.185*h.z*h.z)*(.45+.85*growth);
  vec2 q=(fract(p)-h.xy)/radius+h.xy*2.0-1.0;
  float dome=max(0.0,1.0-dot(q,q));
  return vec3(q*(dome*1.20*mask*vis),mix(avgCov,clamp(dome*3.2,0.0,1.0)*mask,vis));
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
  float clock=fract(weatherSurface.w)*64.0;
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
      float roofUpMask=clamp((weatherUp-.05)*5.0,0.0,1.0);
      float roofSlopeMask=clamp((roofSlopeSin-.02)*10.0,0.0,1.0)*roofUpMask;
      float roofWetStage=weatherExposure(weatherRoof.x,vWeatherOpen);
      float roofWetRaw=roofWetStage*roofUpMask;
      float roofImpervious=1.0-weatherPorosityValue;
      // Porous roofs (asphalt/wood shingles) hold darkening with ground wetness;
      // impervious roofs (metal, smooth tile) follow the faster roof drying ladder.
      float roofPorousRetain=clamp(weatherPorosityValue*2.0-.6,0.0,1.0);
      weatherWet=mix(roofWetStage,weatherWet,roofPorousRetain);
      weatherGlossValue=weatherWet;
      // Impervious roofs (metal, smooth tile) form rivulets, film and beads; porous
      // roofs (asphalt/wood shingles) absorb water so beads soak in and rivulets/film stay faint.
      float roofRivWeight=mix(.12,1.0,roofImpervious*roofImpervious);
      float roofBeadWeight=clamp(roofImpervious*2.0-.5,0.0,1.0);
      vec3 roofNormalOff=vec3(0.0,0.0,0.0);
      float roofWaterCov=0.0,roofRivCov=0.0,roofFilm=0.0;
      #if defined(STANDARD)||defined(PHONG)
      if(roofWetRaw>0.0){
        float roofRate=floor(weatherSurface.w)/255.0;
        float roofFlow=weatherRoof.y;
        float roofFilmRaw=weatherRoof.z;
        float roofTrail=weatherRoof.w;
        float roofPhase=roofFlow>0.0?fract(weatherSurface.w):0.0;
        float roofPx=sqrt(max(dot(weatherWorldDx,weatherWorldDx),dot(weatherWorldDy,weatherWorldDy)));
        vec2 roofVis=clamp((vec2(.048,.075)-roofPx)*vec2(34.0,22.2),0.0,1.0);
        roofFilm=roofFilmRaw*roofSlopeMask*roofRivWeight;
        float roofBeadWash=clamp((roofFilmRaw-.45)*1.82,0.0,1.0);
        if(roofSlopeMask>0.0){
          vec2 roofHoriz=weatherFace.xz/roofSlopeSin;
          vec3 roofAcrossDir=vec3(roofHoriz.y,0.0,-roofHoriz.x);
          vec3 roofDownDir=vec3(roofHoriz.x*weatherUp,-roofSlopeSin,roofHoriz.y*weatherUp);
          vec2 roofUv=vec2(dot(vWeatherWorld,roofAcrossDir),dot(vWeatherWorld,roofDownDir));
          vec3 roofRiv=weatherRoofRivulets(roofUv,roofWetRaw,roofFlow,roofPhase,roofVis.x,roofTrail)*(roofSlopeMask*roofRivWeight);
          vec2 roofFilmSlope=weatherRoofFilm(roofUv,roofFilm,roofRate,roofPhase,roofPx);
          vec2 roofSlope=roofRiv.xy*(1.0-.65*roofBeadWash)+roofFilmSlope;
          roofNormalOff=roofAcrossDir*roofSlope.x+roofDownDir*roofSlope.y;
          roofRivCov=roofRiv.z;
        }
        vec3 roofBead=weatherRoofBeads(vWeatherWorld.xz,roofWetRaw,roofFlow,roofPhase,roofVis.y,(1.0-.94*roofBeadWash)*roofBeadWeight);
        float roofBeadKeep=1.0-roofRivCov;
        roofNormalOff.xz+=roofBead.xy*roofBeadKeep;
        roofWaterCov=min(max(roofRivCov+roofBead.z*roofBeadKeep,roofFilm*.85),1.0);
      }
      #endif
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
    #ifdef WEATHER_SURFACE_ROOF
      float roofCoatWeight=clamp((.4-weatherLum)*3.3333,0.0,1.0)*roofImpervious;
      diffuseColor.rgb *= 1.0-.22*roofRivCov*roofCoatWeight;
    #endif
    diffuseColor.rgb=mix(diffuseColor.rgb,vec3(.85,.87,.9),weatherS);
    #ifdef STANDARD
      #ifdef WEATHER_SURFACE_LAWN
        roughnessFactor=weatherRoughness(mix(roughnessFactor,.42,weatherGlossValue),0.0,weatherP,weatherS);
      #elif defined(WEATHER_SURFACE_ROOF)
        float roofBaseWet=weatherWetRoughness(roughnessFactor,weatherPorosityValue,weatherWet);
        float roofPanelRough=min(max(roofBaseWet,.15-.12*roofFilm),roughnessFactor);
        float roofRough=mix(roofPanelRough,min(roofBaseWet,.03),roofWaterCov);
        roughnessFactor=mix(roofRough,.7,weatherS);
      #else
        roughnessFactor=weatherRoughness(weatherWetRoughness(roughnessFactor,weatherPorosityValue,weatherGlossValue),0.0,weatherP,weatherS);
      #endif
      // Clear dielectric water film shifts dark/painted metals toward untinted
      // water F0 while leaving bright bare metals (galvanized, fire-pit, chrome)
      // metallic so they do not turn into light-grey diffuse plastic when wet.
      float weatherWaterFilmCov=weatherWaterFilm(weatherPorosityValue,weatherWet,weatherP);
      #ifdef WEATHER_SURFACE_ROOF
        weatherWaterFilmCov=max(weatherWaterFilmCov,roofWaterCov);
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
    vec3 weatherNormal=normal+mat3(viewMatrix)*(roofNormalOff*(1.0-weatherS));
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
    float roofSkyGrad=clamp((roofReflected.y-.15)*1.25,0.0,1.0);
    float roofFilmSheen=mix(1.30,2.00,clamp(roofGrazing*.75+roofSkyGrad*.45,0.0,1.0));
    float roofWaterGlint=(roofWaterCov*1.35+roofRivCov*.55)*(.72+.55*roofSkyGrad);
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
  THREE.ShaderChunk.lights_fragment_maps+='\n#if defined(RE_IndirectSpecular)&&defined(WEATHER_SURFACE_ACTIVE)\n#ifdef REFLECTION_PROBE_GROUND\nradiance*=mix(weatherHorizonDamp,1.0,probeActive);\n#else\nradiance*=weatherHorizonDamp;\n#endif\n#endif\n';
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
  const roofUniforms={weatherSurface:uniforms.weatherSurface,weatherRoof:{value:new THREE.Vector4()}};
  const roofWater=createRoofWater();
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
      bindEnvironmentMaterial(material,'weather-surface-'+mode+'-1',mode==='roof'?roofUniforms:uniforms,effect?patchEffect:material.userData.grassUniforms?patches.grass:patches[mode]);
    }}
  }
  const previous=scene.onBeforeRender;
  const walk=oncePerFrame(scene,()=>prepare());
  scene.onBeforeRender=function(renderer,...args){previous.call(this,renderer,...args);walk();};
  return {uniforms,roofUniforms,prepare,
    update(weather={},seconds=0,roof=null) {
      const u=uniforms.weatherSurface.value;
      const r=roofUniforms.weatherRoof.value;
      if(weather.neutral){u.set(0,0,0,0);r.set(0,0,0,0);if(!roof)roofWater.update(weather,seconds);return;}
      const rate=['rain','mix'].includes(weather.precip)?unit(weather.rate):0;
      // Leave one float32 ULP before the next integer at maximum rate, so
      // uploading a phase just before wrap cannot increment the rain rate.
      const phase=Number.isFinite(seconds)?Math.min(((seconds%64+64)%64)/64,1-1/32768):0;
      u.set(unit(weather.wetness),unit(weather.snow_cm/8),unit(weather.puddles),Math.round(rate*255)+phase);
      const rw=roof ?? roofWater.update(weather,seconds);
      const scale=(Number.isFinite(weather.drying_min)&&weather.drying_min>0?Math.max(15,Math.min(1440,weather.drying_min)):180)/180;
      const trail=rw.flow>0?1:rw.stoppedS===null?rw.wet*.65:rw.wet*(1-smooth(240,1140,rw.stoppedS/scale));
      r.set(unit(rw.wet),unit(rw.flow),unit(rw.film),unit(trail));
    },
    dispose(){if(disposed)return;disposed=true;scene.onBeforeRender=previous;},
  };
}
