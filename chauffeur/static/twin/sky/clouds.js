import * as THREE from 'three';
import { overcastFactor } from './overcast.js';
import { generateNoiseVolume, sampleVolume } from './cloud_noise.js';

export const CLOUD_TYPES = Object.freeze({none:0,cumulus:1,stratocumulus:2,stratus:3,nimbostratus:4,cumulonimbus:5});
const types = {sunny:'cumulus',partlycloudy:'cumulus',windy:'cumulus','windy-variant':'cumulus',
  cloudy:'stratocumulus',fog:'nimbostratus',rainy:'nimbostratus',pouring:'nimbostratus',
  snowy:'nimbostratus','snowy-rainy':'nimbostratus',hail:'nimbostratus',exceptional:'nimbostratus',
  lightning:'cumulonimbus','lightning-rainy':'cumulonimbus','clear-night':'none'};
const clamp = x => Math.max(0,Math.min(1,x));
const smooth = (a,b,x) => {const t=clamp((x-a)/Math.max(b-a,1e-6));return t*t*(3-2*t);};
const finite = x => typeof x==='number' && Number.isFinite(x);

// null means absent/invalid, so a genuine zero wind never takes the fallback.
export function windSpeedMps(value,unit) {
  const factor={'km/h':1/3.6,mph:.44704,'m/s':1,kn:.5144}[unit];
  return finite(value) && value>=0 && finite(factor) ? value*factor : null;
}

// `now` is the caller's clock seam; freshness is the existing live-store stale
// flag, never last_changed/last_updated (HA may keep an unchanged state for days).
export function cloudState(weather,{now}={}) {
  const valid=weather && !weather.stale && typeof weather.state==='string' &&
    !['','unknown','unavailable'].includes(weather.state);
  const attributes=valid ? weather.attributes || {} : {};
  const wind=windSpeedMps(attributes.wind_speed,attributes.wind_speed_unit);
  const bearing=finite(attributes.wind_bearing) ? attributes.wind_bearing : 270;
  return {coverage:valid ? overcastFactor(weather) : 0,type:valid ? types[weather.state] ?? 'cumulus' : 'none',
    windMps:wind ?? 3,windToDeg:((bearing+180)%360+360)%360,
    lightning:!!valid && (weather.state==='lightning' || weather.state==='lightning-rainy')};
}

// Geographic east/north metres, deliberately independent of the house's facing.
// The caller rotates to model axes using the site's north and converts scene feet
// to metres. Feed this displacement to cloudOffset; detail evolves 1.3x faster.
export function cloudDrift(state,seconds) {
  const speedMps=Math.max(2,state.windMps*2)*6, angle=state.windToDeg*Math.PI/180;
  return {speedMps,eastM:Math.sin(angle)*speedMps*seconds,northM:Math.cos(angle)*speedMps*seconds};
}

export function createCloudNoise({size=128,detail=32}={}) {
  // Generate before allocating textures, so invalid sizes cannot leak a GPU object.
  const baseData=generateNoiseVolume(size), detailData=generateNoiseVolume(detail,{detail:true});
  function texture(data,n,name) {
    const result=new THREE.Data3DTexture(data,n,n,n);
    result.name=name;result.format=THREE.RGBAFormat;result.type=THREE.UnsignedByteType;
    result.wrapS=result.wrapT=result.wrapR=THREE.RepeatWrapping;
    result.minFilter=result.magFilter=THREE.LinearFilter;
    result.generateMipmaps=false;result.unpackAlignment=1;result.needsUpdate=true;
    return result;
  }
  const base=texture(baseData,size,'twin-cloud-base'), erosion=texture(detailData,detail,'twin-cloud-detail');
  let disposed=false;
  return {base,detail:erosion,dispose(){if(disposed)return;disposed=true;base.dispose();erosion.dispose();}};
}

// CPU port of cloudDensity, with the same periodic trilinear samples and remaps.
// p and offset are local metres above ground at the origin, y up. The curved
// Earth shell makes even a horizontal panel-camera ray reach distant clouds.
export function sampleCloudDensity(p,{base,detail,coverage=0,type='none',offset=[0,0,0]}={}) {
  const kind=typeof type==='number' ? type : CLOUD_TYPES[type] || 0;
  if (coverage<=0 || kind<.5) return 0;
  const low=kind>2.5 && kind<4.5, bottom=low?500:1500, top=low?1500:4000;
  const altitude=Math.hypot(p[0],p[1]+6360000,p[2])-6360000;
  const h=(altitude-bottom)/(top-bottom);
  if (h<=0 || h>=1) return 0;
  const q=p.map((v,i)=>v-offset[i]);
  const n=sampleVolume(base.image,[q[0]/12000,h*.38-q[1]/12000,q[2]/12000]);
  const weather=sampleVolume(base.image,[q[0]/48000,.37,q[2]/48000]);
  const local=clamp(coverage*1.35-(1-(weather[1]*.625+weather[2]*.25+weather[3]*.125))*.35);
  let profile=smooth(0,.12,h)*(1-smooth(.55,1,h));
  if (kind>1.5 && kind<2.5) profile=smooth(0,.08,h)*(1-smooth(.35,.72,h));
  if (low) profile=smooth(0,.06,h)*(1-smooth(.85,1,h));
  if (kind>4.5) profile=smooth(0,.1,h)*(1-smooth(.82,1,h));
  const shape=low ? .6+.4*n[0] : n[0];
  const body=clamp((shape*profile-(1-local))/Math.max(local,1e-4));
  const d=sampleVolume(detail.image,p.map((v,i)=>(v-offset[i]*1.3)/1800));
  const erosion=(1-(d[1]*.625+d[2]*.25+d[3]*.125))*(low?.12:.28)*(1-body);
  return clamp((body-erosion)/Math.max(1-erosion,1e-4));
}

// Shared verbatim by screen, cube and shadow passes; WebGL2 / three r187.
// All positions/displacements are METRES, not the atmosphere's km or scene feet.
// cloudType = CLOUD_TYPES[state.type]; all weather/drift/light changes are uniforms.
// Radiances: scene-linear RGB (sun = atmosphere transmittance * SUN=10; moon =
// caller's lunar radiance including phase). Ambient colours are sky/ground
// radiances. marchClouds returns premultiplied radiance RGB and opacity (1-T).
// maxSteps is bounded to 1..128; jitter is a [0,1] blue-noise start offset.
export const CLOUD_GLSL = `
uniform sampler3D cloudBaseNoise;
uniform sampler3D cloudDetailNoise;
uniform float cloudCoverage;
uniform float cloudType;
uniform vec3 cloudOffset;
uniform vec3 cloudSunRadiance;
uniform vec3 cloudMoonDir;
uniform vec3 cloudMoonRadiance;
uniform vec3 cloudAmbientTop;
uniform vec3 cloudAmbientBottom;
const float CLOUD_EARTH=6360000.0;
const float CLOUD_EXTINCTION=0.0025;
vec3 cloudUnit(vec3 d) { return length(d)>1e-6 ? d/max(length(d),1e-6) : vec3(0.0,1.0,0.0); }
vec2 cloudLayer() { return cloudType>2.5 && cloudType<4.5 ? vec2(500.0,1500.0) : vec2(1500.0,4000.0); }
float cloudHeight(vec3 p) { return length(p+vec3(0.0,CLOUD_EARTH,0.0))-CLOUD_EARTH; }
vec2 cloudSphere(vec3 p,vec3 d,float radius) {
  vec3 q=p+vec3(0.0,CLOUD_EARTH,0.0);
  float b=dot(q,d), r=length(q), discriminant=b*b-(r-radius)*(r+radius);
  if(discriminant<0.0) return vec2(-1.0);
  return -b+vec2(-1.0,1.0)*sqrt(max(0.0,discriminant));
}
// Nearest connected piece of the shell; excludes the far side of Earth.
vec2 cloudSegment(vec3 p,vec3 d) {
  vec2 layer=cloudLayer(), outer=cloudSphere(p,d,CLOUD_EARTH+layer.y);
  if(outer.y<=0.0) return vec2(0.0);
  float start=max(0.0,outer.x), end=min(outer.y,250000.0);
  vec2 inner=cloudSphere(p,d,CLOUD_EARTH+layer.x);
  if(cloudHeight(p)<layer.x) start=max(start,inner.y);
  else if(inner.x>0.0) end=min(end,inner.x);
  vec2 ground=cloudSphere(p,d,CLOUD_EARTH);
  if(ground.x>0.0) end=min(end,ground.x);
  return end>start ? vec2(start,end) : vec2(0.0);
}
float cloudDensity(vec3 p) {
  if(cloudCoverage<=0.0 || cloudType<0.5) return 0.0;
  vec2 layer=cloudLayer();
  float h=(cloudHeight(p)-layer.x)/max(layer.y-layer.x,1e-4);
  if(h<=0.0 || h>=1.0) return 0.0;
  vec3 q=p-cloudOffset;
  vec4 n=texture(cloudBaseNoise,vec3(q.x/12000.0,h*0.38-q.y/12000.0,q.z/12000.0));
  vec4 weather=texture(cloudBaseNoise,vec3(q.x/48000.0,0.37,q.z/48000.0));
  float local=clamp(cloudCoverage*1.35-(1.0-dot(weather.gba,vec3(0.625,0.25,0.125)))*0.35,0.0,1.0);
  bool low=cloudType>2.5 && cloudType<4.5;
  float profile=smoothstep(0.0,0.12,h)*(1.0-smoothstep(0.55,1.0,h));
  if(cloudType>1.5 && cloudType<2.5) profile=smoothstep(0.0,0.08,h)*(1.0-smoothstep(0.35,0.72,h));
  if(low) profile=smoothstep(0.0,0.06,h)*(1.0-smoothstep(0.85,1.0,h));
  if(cloudType>4.5) profile=smoothstep(0.0,0.1,h)*(1.0-smoothstep(0.82,1.0,h));
  float shape=low ? 0.6+0.4*n.r : n.r;
  float body=clamp((shape*profile-(1.0-local))/max(local,1e-4),0.0,1.0);
  vec4 detail=texture(cloudDetailNoise,(p-cloudOffset*1.3)/1800.0);
  float erosion=(1.0-dot(detail.gba,vec3(0.625,0.25,0.125)))*(low ? 0.12 : 0.28)*(1.0-body);
  return clamp((body-erosion)/max(1.0-erosion,1e-4),0.0,1.0);
}
// Direct Beer-Lambert transmittance towards either luminary. Geometric Earth
// occlusion permits twilight illumination of cloud tops but no light through soil.
float cloudLight(vec3 p,vec3 sunDir) {
  vec3 d=cloudUnit(sunDir);
  if(cloudSphere(p,d,CLOUD_EARTH).x>0.0) return 0.0;
  vec2 segment=cloudSegment(p,d);
  float depth=0.0;
  for(int j=0;j<6;j++) {
    float u=float(j)/6.0,v=float(j+1)/6.0;
    float a=mix(segment.x,segment.y,u*u),b=mix(segment.x,segment.y,v*v);
    depth+=cloudDensity(p+d*((a+b)*0.5))*(b-a)*CLOUD_EXTINCTION;
  }
  return exp(-max(0.0,depth));
}
float cloudHG(float mu,float g) {
  return (1.0-g*g)/max(12.56637061*pow(max(1e-4,1.0+g*g-2.0*g*mu),1.5),1e-6);
}
float cloudScatter(float transmission,float mu) {
  if(transmission<=0.0) return 0.0;
  float depth=-log(max(transmission,1e-6)), energy=1.0, attenuation=1.0, eccentricity=1.0, result=0.0;
  // Three Wrenninge-style scattering orders: broader, less extinguished light.
  for(int octave=0;octave<3;octave++) {
    float phase=0.85*cloudHG(mu,0.8*eccentricity)+0.15*cloudHG(mu,-0.3*eccentricity);
    result+=energy*exp(-depth*attenuation)*phase;
    energy*=0.5;attenuation*=0.5;eccentricity*=0.5;
  }
  float powder=1.0-exp(-2.0*depth);
  return result*(0.5+0.5*powder);
}
float cloudHeld(float v) { return v>=0.0 ? min(v,4096.0) : 0.0; }
vec4 marchClouds(vec3 ro,vec3 rd,float maxSteps,float jitter,vec3 sunDir) {
  if(cloudCoverage<=0.0 || cloudType<0.5) return vec4(0.0);
  vec3 d=cloudUnit(rd),sun=cloudUnit(sunDir),moon=cloudUnit(cloudMoonDir);
  vec2 segment=cloudSegment(ro,d),layer=cloudLayer();
  float steps=clamp(floor(maxSteps),1.0,128.0),ds=max(0.0,segment.y-segment.x)/max(steps,1.0);
  if(ds<=0.0) return vec4(0.0);
  vec3 radiance=vec3(0.0);
  float transmission=1.0;
  for(int j=0;j<128;j++) {
    if(float(j)>=steps || transmission<0.005) break;
    vec3 p=ro+d*(segment.x+(float(j)+clamp(jitter,0.0,1.0))*ds);
    float density=cloudDensity(p);
    if(density<=0.0) continue;
    float stepT=exp(-density*ds*CLOUD_EXTINCTION);
    float h=clamp((cloudHeight(p)-layer.x)/max(layer.y-layer.x,1e-4),0.0,1.0);
    vec3 light=mix(cloudAmbientBottom,cloudAmbientTop,h)*0.5;
    if(dot(cloudSunRadiance,cloudSunRadiance)>0.0) light+=cloudSunRadiance*cloudScatter(cloudLight(p,sun),dot(d,sun));
    if(dot(cloudMoonRadiance,cloudMoonRadiance)>0.0) light+=cloudMoonRadiance*cloudScatter(cloudLight(p,moon),dot(d,moon));
    radiance+=transmission*(1.0-stepT)*light;
    transmission*=stepT;
  }
  float opacity=1.0-transmission;
  return vec4(cloudHeld(radiance.r),cloudHeld(radiance.g),cloudHeld(radiance.b),opacity>=0.0 ? min(opacity,1.0) : 0.0);
}
`;
