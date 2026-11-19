import * as THREE from 'three';

// Earth in km, coefficients in km^-1 (Hillaire 2020, table 1; Bruneton's RGB wavelengths).
const R = 6360, TOP = 6460, HEIGHT = .002, HR = 8, HM = 1.2, G = .8;
const RAYLEIGH = [.005802,.013558,.0331], OZONE = [.000650,.001881,.000085];
const MIE = .003996, MIE_EXT = MIE / .9, SUN = 10;
// The night-vision floor must survive the ACES toe at the existing 1.2 night exposure.
const AIRGLOW = [.008845,.012168,.021506], ALBEDO = [.18,.20,.14];
const VIEW_STEPS = 16, LIGHT_STEPS = 8;
const clamp = (x,a=0,b=1) => Math.max(a,Math.min(b,x));
const dot = (a,b) => a.reduce((s,v,i) => s+v*b[i],0);
const length = a => Math.sqrt(Math.max(0,dot(a,a)));
const unit = a => { const v = a?.isVector3 ? a.toArray() : a || [0,1,0], n = Math.max(length(v),1e-6); return v.map(x=>x/n); };
const along = (p,d,t) => p.map((x,i)=>x+d[i]*t);
const origin = [0,R+HEIGHT,0];
function sphere(p,d,r) {
  const b=dot(p,d), radius=length(p), h=b*b-(radius-r)*(radius+r);
  return h<0 ? [-1,-1] : [-b-Math.sqrt(Math.max(0,h)),-b+Math.sqrt(Math.max(0,h))];
}
function density(p) {
  const h=Math.max(0,length(p)-R);
  return [Math.exp(-h/HR),Math.exp(-h/HM),Math.max(0,1-Math.abs(h-25)/15)];
}
function extinction(d,i) { return RAYLEIGH[i]*d[0]+MIE_EXT*d[1]+OZONE[i]*d[2]; }
function lightTransmission(p,d) {
  if (sphere(p,d,R)[0]>0) return [0,0,0];
  const end=Math.max(0,sphere(p,d,TOP)[1]), depth=[0,0,0];
  for (let j=0;j<LIGHT_STEPS;j++) {
    const a=end*(j/LIGHT_STEPS)**2, b=end*((j+1)/LIGHT_STEPS)**2;
    const rho=density(along(p,d,(a+b)*.5));
    for (let i=0;i<3;i++) depth[i]+=extinction(rho,i)*(b-a);
  }
  return depth.map(v=>Math.exp(-v));
}
export function transmittance(dirWorld) { return lightTransmission(origin,unit(dirWorld)); }

// CPU quadrature mirrors the shader for the hemisphere/haze consumers and offline safety tests.
export function sampleRadiance(dirWorld, {sunDir=[0,1,0],moonDir=[0,-1,0],moonFraction=0,overcast=0} = {}) {
  const d=unit(dirWorld), sun=unit(sunDir), moon=unit(moonDir), c=clamp(overcast);
  const hit=sphere(origin,d,R)[0], end=hit>0 ? hit : sphere(origin,d,TOP)[1];
  const mu=clamp(dot(d,sun),-1,1), rayPhase=3/(16*Math.PI)*(1+mu*mu);
  const miePhase=3/(8*Math.PI)*(1-G*G)*(1+mu*mu)/Math.max((2+G*G)*Math.pow(Math.max(1e-4,1+G*G-2*G*mu),1.5),1e-6);
  const result=[0,0,0], transmission=[1,1,1];
  for (let j=0;j<VIEW_STEPS;j++) {
    const a=end*(j/VIEW_STEPS)**2, b=end*((j+1)/VIEW_STEPS)**2, ds=b-a;
    const p=along(origin,d,(a+b)*.5), rho=density(p), light=lightTransmission(p,sun);
    for (let i=0;i<3;i++) {
      const ext=extinction(rho,i), step=Math.exp(-ext*ds);
      result[i]+=transmission[i]*light[i]*(RAYLEIGH[i]*rho[0]*rayPhase+MIE*rho[1]*miePhase)*(1-step)/Math.max(ext,1e-6)*SUN;
      transmission[i]*=step;
    }
  }
  if (hit>0) {
    const p=along(origin,d,Math.max(0,hit-.001)), normal=unit(p), light=lightTransmission(p,sun), sky=lightTransmission(origin,[0,1,0]);
    for (let i=0;i<3;i++) result[i]+=transmission[i]*ALBEDO[i]/Math.PI*SUN*
      (light[i]*Math.max(0,dot(normal,sun))+(1-sky[i])*.25*clamp(sun[1]+.1));
  }
  // Airglow survives astronomical night. Lunar fill is small; discs/stars belong to Task 3.
  for (let i=0;i<3;i++) result[i]+=AIRGLOW[i]*(1+clamp(moonFraction)*Math.max(0,moon[1])*(1-c));
  const luminance=dot(result,[.2126,.7152,.0722]);
  // CIE overcast's (1+2 sin altitude)/3 gives a bright zenith and a grey horizon.
  const grey=luminance*(1+2*Math.max(0,d[1]))/3;
  const blend=c*(.75+.25*(1-Math.max(0,d[1])));
  return result.map(v=>clamp(v*(1-blend)+grey*blend,0,4096));
}

const vec = a => `vec3(${a.map(v=>Number(v).toFixed(8)).join(',')})`;
const fragmentShader = `
uniform vec3 sunDir;
uniform vec3 moonDir;
uniform float moonFraction;
uniform float overcast;
varying vec3 skyDirection;
const float R = ${R.toFixed(1)}, TOP = ${TOP.toFixed(1)}, SUN = ${SUN.toFixed(1)};
const vec3 BETA_R = ${vec(RAYLEIGH)}, BETA_O = ${vec(OZONE)};
vec2 sphere(vec3 p, vec3 d, float radius) {
  float b=dot(p,d), r=length(p), h=b*b-(r-radius)*(r+radius);
  if(h<0.0) return vec2(-1.0);
  return -b+vec2(-1.0,1.0)*sqrt(max(0.0,h));
}
vec3 density(vec3 p) {
  float h=max(0.0,length(p)-R);
  return vec3(exp(-h/${HR.toFixed(1)}),exp(-h/${HM.toFixed(1)}),max(0.0,1.0-abs(h-25.0)/15.0));
}
vec3 extinction(vec3 rho) { return BETA_R*rho.x+vec3(${MIE_EXT.toFixed(8)})*rho.y+BETA_O*rho.z; }
vec3 lightTransmission(vec3 p, vec3 d) {
  if(sphere(p,d,R).x>0.0) return vec3(0.0);
  float end=max(0.0,sphere(p,d,TOP).y);
  vec3 depth=vec3(0.0);
  for(int j=0;j<${LIGHT_STEPS};j++) {
    float u=float(j)/${LIGHT_STEPS.toFixed(1)}, v=float(j+1)/${LIGHT_STEPS.toFixed(1)};
    float a=end*u*u, b=end*v*v;
    depth+=extinction(density(p+d*((a+b)*0.5)))*(b-a);
  }
  return exp(-depth);
}
void main() {
  vec3 d=skyDirection/max(length(skyDirection),1e-6), origin=vec3(0.0,R+${HEIGHT.toFixed(4)},0.0);
  float hit=sphere(origin,d,R).x, end=hit>0.0 ? hit : sphere(origin,d,TOP).y;
  float mu=clamp(dot(d,sunDir),-1.0,1.0);
  float rayPhase=3.0/(16.0*3.14159265)*(1.0+mu*mu);
  float miePhase=3.0/(8.0*3.14159265)*(1.0-${G*G})*(1.0+mu*mu)/
    max((2.0+${G*G})*pow(max(1e-4,1.0+${G*G}-2.0*${G}*mu),1.5),1e-6);
  vec3 result=vec3(0.0), transmission=vec3(1.0);
  for(int j=0;j<${VIEW_STEPS};j++) {
    float u=float(j)/${VIEW_STEPS.toFixed(1)}, v=float(j+1)/${VIEW_STEPS.toFixed(1)};
    float a=end*u*u, b=end*v*v;
    vec3 p=origin+d*((a+b)*0.5), rho=density(p), light=lightTransmission(p,sunDir);
    vec3 ext=extinction(rho), stepT=exp(-ext*(b-a));
    result+=transmission*light*(BETA_R*rho.x*rayPhase+vec3(${MIE.toFixed(8)})*rho.y*miePhase)*
      (vec3(1.0)-stepT)/max(ext,vec3(1e-6))*SUN;
    transmission*=stepT;
  }
  if(hit>0.0) {
    vec3 p=origin+d*max(0.0,hit-0.001), normal=p/max(length(p),1e-6);
    vec3 light=lightTransmission(p,sunDir), sky=lightTransmission(origin,vec3(0.0,1.0,0.0));
    result+=transmission*${vec(ALBEDO)}/3.14159265*SUN*
      (light*max(0.0,dot(normal,sunDir))+(vec3(1.0)-sky)*0.25*clamp(sunDir.y+0.1,0.0,1.0));
  }
  result+=${vec(AIRGLOW)}*(1.0+moonFraction*max(0.0,moonDir.y)*(1.0-overcast));
  float luminance=dot(result,vec3(0.2126,0.7152,0.0722));
  float grey=luminance*(1.0+2.0*max(0.0,d.y))/3.0;
  float blend=overcast*(0.75+0.25*(1.0-max(0.0,d.y)));
  result=mix(result,vec3(grey),blend);
  // A comparison also catches NaN; protect every consumer, including low without bloom.
  gl_FragColor=vec4(result.r>=0.0 ? min(result.r,4096.0) : 0.0,
    result.g>=0.0 ? min(result.g,4096.0) : 0.0,result.b>=0.0 ? min(result.b,4096.0) : 0.0,1.0);
}`;

export function createSky(renderer, {tier='low'} = {}) {
  const size=['high','max'].includes(tier) ? 512 : 256;
  const target=new THREE.WebGLCubeRenderTarget(size,{type:THREE.HalfFloatType,colorSpace:THREE.LinearSRGBColorSpace,
    depthBuffer:false,generateMipmaps:false,minFilter:THREE.LinearFilter});
  target.texture.name='twin-sky';
  const uniforms={sunDir:{value:new THREE.Vector3(0,1,0)},moonDir:{value:new THREE.Vector3(0,-1,0)},moonFraction:{value:0},overcast:{value:0}};
  const material=new THREE.ShaderMaterial({uniforms,fragmentShader,side:THREE.BackSide,depthTest:false,depthWrite:false,toneMapped:false,
    vertexShader:'varying vec3 skyDirection; void main(){ skyDirection=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }'});
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(2,2,2),material);mesh.frustumCulled=false;
  const scene=new THREE.Scene();scene.name='twin-atmosphere';scene.add(mesh);
  const camera=new THREE.CubeCamera(.1,10,target), pmrem=new THREE.PMREMGenerator(renderer);
  let environmentTarget=null, previous=null, disposed=false;
  function update(input={}) {
    if (disposed) return false;
    const next={...input,sunDir:unit(input.sunDir),moonDir:unit(input.moonDir || [0,-1,0]),moonFraction:clamp(input.moonFraction || 0),overcast:clamp(input.overcast || 0)};
    const moved=(a,b)=>dot(a,b)<Math.cos(.25*Math.PI/180);
    if (previous && !input.force && !moved(next.sunDir,previous.sunDir) && !moved(next.moonDir,previous.moonDir) &&
        Math.abs(next.overcast-previous.overcast)<=.05 && Math.abs(next.moonFraction-previous.moonFraction)<.001) return false;
    uniforms.sunDir.value.fromArray(next.sunDir);uniforms.moonDir.value.fromArray(next.moonDir);
    uniforms.moonFraction.value=next.moonFraction;uniforms.overcast.value=next.overcast;
    const saved={target:renderer.getRenderTarget(),face:renderer.getActiveCubeFace(),mip:renderer.getActiveMipmapLevel(),
      xr:renderer.xr.enabled,auto:renderer.autoClear,info:{...renderer.info.render},mipmaps:target.texture.mipmapsAutoUpdate};
    try {
      renderer.autoClear=true;
      camera.update(renderer,scene);
      // r187 keys envMapSize/MaxLod/PMREM: retain this target and its mip layout forever.
      environmentTarget=pmrem.fromCubemap(target.texture,environmentTarget);
      previous=next;
      return true;
    } finally {
      renderer.setRenderTarget(saved.target,saved.face,saved.mip);renderer.xr.enabled=saved.xr;renderer.autoClear=saved.auto;
      target.texture.mipmapsAutoUpdate=saved.mipmaps;Object.assign(renderer.info.render,saved.info);
    }
  }
  try { update({sunDir:[0,1,0],force:true}); }
  catch (error) { dispose();throw error; }
  function dispose() {
    if (disposed) return;
    disposed=true;target.dispose();environmentTarget?.dispose();pmrem.dispose();mesh.geometry.dispose();material.dispose();
  }
  return {cube:target.texture,get environment(){return environmentTarget.texture;},update,
    horizon:dir=>new THREE.Color().setRGB(...sampleRadiance(dir,previous || {})),dispose};
}
