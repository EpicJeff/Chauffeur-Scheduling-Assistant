import * as THREE from 'three';
import { createBodies } from './bodies.js';
import { createStars } from './stars.js';
import { CLOUD_GLSL, createCloudUniforms } from './clouds.js';

// Earth in km, coefficients in km^-1 (Hillaire 2020, table 1; Bruneton's RGB wavelengths).
const R = 6360, TOP = 6460, HEIGHT = .002, HR = 8, HM = 1.2, G = .8;
const RAYLEIGH = [.005802,.013558,.0331], OZONE = [.000650,.001881,.000085];
const MIE = .003996, MIE_EXT = MIE / .9, SUN = 10;
// The night-vision floor must survive the ACES toe at the existing 1.2 night exposure.
const AIRGLOW = [.008845,.012168,.021506], ALBEDO = [.18,.20,.14];
const GROUND_START = Math.sin(Math.PI/180), GROUND_END = Math.sin(15*Math.PI/180);
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

// The existing first-scatter hemisphere estimate: a quarter of the removed
// vertical beam, fading through civil twilight. Weather uses the light factors
// from lookAt; the airglow/lunar floor is reflected, never emitted by the soil.
function groundRadiance({sunDir=[0,1,0],moonDir=[0,-1,0],moonFraction=0,overcast=0} = {}) {
  const sun=unit(sunDir), moon=unit(moonDir), c=clamp(overcast);
  const direct=transmittance(sun), vertical=transmittance([0,1,0]);
  return ALBEDO.map((a,i)=>a*((SUN*direct[i]*Math.max(0,sun[1])*(1-.75*c)+
    SUN*(1-vertical[i])*.25*clamp(sun[1]+.1)*(1+.35*c))/Math.PI+
    AIRGLOW[i]*(1+clamp(moonFraction)*Math.max(0,moon[1])*(1-c))));
}

// CPU quadrature mirrors the shader for the hemisphere/haze consumers and offline safety tests.
export function sampleRadiance(dirWorld, {sunDir=[0,1,0],moonDir=[0,-1,0],moonFraction=0,overcast=0} = {}) {
  let d=unit(dirWorld);
  const below=Math.max(0,-d[1]);
  // Evaluate the horizon's in-scattering at this azimuth, then blend to soil.
  // The nadir has no azimuth, so use +z rather than divide by zero.
  if (d[1]<0) {
    const horizontal=Math.hypot(d[0],d[2]);
    d=horizontal>1e-6 ? [d[0]/horizontal,0,d[2]/horizontal] : [0,0,1];
  }
  const sun=unit(sunDir), moon=unit(moonDir), c=clamp(overcast);
  const end=sphere(origin,d,TOP)[1];
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
  // Airglow survives astronomical night; detailed bodies are separate meshes.
  for (let i=0;i<3;i++) result[i]+=AIRGLOW[i]*(1+clamp(moonFraction)*Math.max(0,moon[1])*(1-c));
  const ground=below>0 ? groundRadiance({sunDir,moonDir,moonFraction,overcast}) : [0,0,0];
  const t=clamp((below-GROUND_START)/(GROUND_END-GROUND_START)), groundWeight=t*t*(3-2*t);
  return result.map((v,i)=>clamp(v*(1-groundWeight)+ground[i]*groundWeight,0,4096));
}

// Cosine-weighted quadrature of both hemispheres, in scene-linear irradiance/pi.
// Four Gauss-Legendre elevation nodes x eight azimuths include the bright low
// sunset sky (lowest node is 4 degrees) and distant ground. Align one azimuth
// with the sun; evaluate only on light-state updates, never in a fragment.
export function sampleSkyIrradiance(state={}) {
  const top=[0,0,0],bottom=[0,0,0];
  const nodes=[.0694318442,.3300094782,.6699905218,.9305681558];
  const weights=[.1739274226,.3260725774,.3260725774,.1739274226];
  const sun=unit(state.sunDir),bearing=Math.atan2(sun[2],sun[0]);
  for(let ring=0;ring<4;ring++)for(let azimuth=0;azimuth<8;azimuth++) {
    const y=nodes[ring],r=Math.sqrt(1-y*y),a=bearing+azimuth*Math.PI/4;
    for(const [hemisphere,sign] of [[top,1],[bottom,-1]]) {
      const radiance=sampleRadiance([r*Math.cos(a),sign*y,r*Math.sin(a)],state);
      for(let i=0;i<3;i++)hemisphere[i]+=radiance[i]*weights[ring]*2*y/8;
    }
  }
  return {top,bottom};
}

const vec = a => `vec3(${a.map(v=>Number(v).toFixed(8)).join(',')})`;
const fragmentShader = `
precision highp sampler3D;
${CLOUD_GLSL}
uniform float cloudViewEnabled,cloudCubeSteps;
uniform vec3 sunDir;
uniform vec3 moonDir;
uniform float moonFraction;
uniform float overcast;
uniform vec3 groundColour;
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
  float below=max(0.0,-d.y);
  if(d.y<0.0) {
    float horizontal=length(d.xz);
    d=horizontal>1e-6 ? vec3(d.x,0.0,d.z)/max(horizontal,1e-6) : vec3(0.0,0.0,1.0);
  }
  float end=sphere(origin,d,TOP).y;
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
  result+=${vec(AIRGLOW)}*(1.0+moonFraction*max(0.0,moonDir.y)*(1.0-overcast));
  // Angular aerial-perspective approximation: horizon through 1 degree,
  // smooth transition to lit ground by 15 degrees. Same ramp as CPU sampling.
  float groundWeight=smoothstep(${GROUND_START},${GROUND_END},below);
  result=mix(result,groundColour,groundWeight);
  if(cloudViewEnabled>0.5) {
    vec4 cloud=marchClouds(vec3(0.0,${(HEIGHT*1000).toFixed(1)},0.0),cloudUnit(skyDirection),cloudCubeSteps,0.5,sunDir,result);
    result=cloud.rgb+result*(1.0-cloud.a);
  }
  // A comparison also catches NaN; protect every consumer, including low without bloom.
  gl_FragColor=vec4(result.r>=0.0 ? min(result.r,4096.0) : 0.0,
    result.g>=0.0 ? min(result.g,4096.0) : 0.0,result.b>=0.0 ? min(result.b,4096.0) : 0.0,1.0);
}`;

export function createSky(renderer, {tier='low',clouds=null} = {}) {
  const size=['high','max'].includes(tier) ? 512 : 256;
  const target=new THREE.WebGLCubeRenderTarget(size,{type:THREE.HalfFloatType,colorSpace:THREE.LinearSRGBColorSpace,
    depthBuffer:false,generateMipmaps:false,minFilter:THREE.LinearFilter});
  target.texture.name='twin-sky';
  const clearTarget=clouds?.screen ? target.clone() : null;
  if(clearTarget)clearTarget.texture.name='twin-clear-sky';
  const cloudUniforms=createCloudUniforms();
  function snapshotClouds() {
    if(!clouds)return;
    for(const [key,u] of Object.entries(cloudUniforms)) {
      // A coherent six-frame capture outlasts an 80-160 ms pulse. Never bake a
      // transient flash into a cube/PMREM that persists for another four seconds.
      if(key==='cloudLightning'){u.value.set(0,0,0,0);continue;}
      const value=clouds.uniforms[key].value;
      if(u.value?.isVector3)u.value.copy(value);else u.value=value;
    }
  }
  snapshotClouds();
  const uniforms={...cloudUniforms,cloudViewEnabled:{value:1},cloudCubeSteps:{value:16},sunDir:{value:new THREE.Vector3(0,1,0)},moonDir:{value:new THREE.Vector3(0,-1,0)},moonFraction:{value:0},overcast:{value:0},groundColour:{value:new THREE.Vector3()}};
  const material=new THREE.ShaderMaterial({uniforms,fragmentShader,side:THREE.BackSide,depthTest:false,depthWrite:false,toneMapped:false,
    vertexShader:'varying vec3 skyDirection; void main(){ skyDirection=position; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }'});
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(2,2,2),material);mesh.frustumCulled=false;
  const scene=new THREE.Scene();scene.name='twin-atmosphere';scene.add(mesh);
  const directClouds={cloudUniforms:clouds?.uniforms || cloudUniforms,cloudAttenuate:!clouds?.screen};
  const bodies=createBodies(directClouds), stars=createStars(null,directClouds),
    cubeBodies=createBodies({cloudUniforms,cloudAttenuate:true}),cubeStars=createStars(null,{cloudUniforms,cloudAttenuate:true});
  const object=new THREE.Group();object.name='twin-celestial';object.add(bodies.object,stars.object);
  scene.add(cubeBodies.object,cubeStars.object);
  // Shells are at 40/60m, inside even the smallest house reflection camera.
  const camera=new THREE.CubeCamera(.1,100,target), pmrem=new THREE.PMREMGenerator(renderer);
  let environmentTarget=null, previous=null, disposed=false;
  let pendingFace=null,lastCloudRefresh=-Infinity,frameSeconds=0;
  let moonTexture=null, assetPromise=null;
  function update(input={}) {
    if (disposed) return false;
    const next={...input,sunDir:unit(input.sunDir),moonDir:unit(input.moonDir || [0,-1,0]),moonFraction:clamp(input.moonFraction || 0),overcast:clamp(input.overcast || 0)};
    const bodyInput={...next,transmittance};
    const starInput={...next,overcast:clouds?0:next.overcast,latitudeRad:next.latitudeRad ?? (next.latitude || 0)*Math.PI/180,
      sunAltDeg:Math.asin(clamp(next.sunDir[1],-1,1))*180/Math.PI,
      moonFraction:next.moonFraction*Math.max(0,next.moonDir[1])};
    // Direct-view uniforms follow even steps below the cube's refresh threshold.
    bodies.update(bodyInput);stars.update(starInput);
    const moved=(a,b)=>dot(a,b)<Math.cos(.25*Math.PI/180);
    if (previous && !input.force && !moved(next.sunDir,previous.sunDir) && !moved(next.moonDir,previous.moonDir) &&
        Math.abs(next.overcast-previous.overcast)<=.05 && Math.abs(next.moonFraction-previous.moonFraction)<.001) return false;
    uniforms.sunDir.value.fromArray(next.sunDir);uniforms.moonDir.value.fromArray(next.moonDir);
    uniforms.moonFraction.value=next.moonFraction;uniforms.overcast.value=next.overcast;
    uniforms.groundColour.value.fromArray(groundRadiance(next));
    cubeBodies.update(bodyInput);cubeStars.update(starInput);
    snapshotClouds();
    const saved={target:renderer.getRenderTarget(),face:renderer.getActiveCubeFace(),mip:renderer.getActiveMipmapLevel(),
      xr:renderer.xr.enabled,auto:renderer.autoClear,info:{...renderer.info.render},mipmaps:target.texture.mipmapsAutoUpdate};
    try {
      renderer.autoClear=true;
      if(clearTarget) {
        uniforms.cloudViewEnabled.value=0;cubeBodies.setCloudsEnabled(false);cubeStars.setCloudsEnabled(false);
        // The screen's aerial-perspective lookup needs atmosphere alone. Direct
        // celestial meshes already draw over this background; keep bright discs
        // out of the in-scattering colour behind an opaque distant cloud.
        const visible=[cubeBodies.object.visible,cubeStars.object.visible];
        try {
          cubeBodies.object.visible=false;cubeStars.object.visible=false;
          camera.renderTarget=clearTarget;camera.update(renderer,scene);
        } finally {
          [cubeBodies.object.visible,cubeStars.object.visible]=visible;camera.renderTarget=target;
        }
      }
      uniforms.cloudViewEnabled.value=1;cubeBodies.setCloudsEnabled(true);cubeStars.setCloudsEnabled(true);
      // First draw allocates the fixed PMREM while noise is still unavailable.
      // Later cloudy refreshes submit one face per animation frame.
      if(previous&&clouds?.active){pendingFace=0;lastCloudRefresh=frameSeconds;}
      else {pendingFace=null;camera.update(renderer,scene);}
      // r187 keys envMapSize/MaxLod/PMREM: retain this target and its mip layout forever.
      if(pendingFace===null)environmentTarget=pmrem.fromCubemap(target.texture,environmentTarget);
      previous=next;
      return true;
    } finally {
      camera.renderTarget=target;uniforms.cloudViewEnabled.value=1;cubeBodies.setCloudsEnabled(true);cubeStars.setCloudsEnabled(true);
      renderer.setRenderTarget(saved.target,saved.face,saved.mip);renderer.xr.enabled=saved.xr;renderer.autoClear=saved.auto;
      target.texture.mipmapsAutoUpdate=saved.mipmaps;Object.assign(renderer.info.render,saved.info);
    }
  }
  try { update({sunDir:[0,1,0],force:true}); }
  catch (error) { dispose();throw error; }
  function dispose() {
    if (disposed) return;
    disposed=true;target.dispose();clearTarget?.dispose();environmentTarget?.dispose();pmrem.dispose();mesh.geometry.dispose();material.dispose();
    for (const layer of [bodies,stars,cubeBodies,cubeStars]) layer.dispose();
    moonTexture?.dispose();object.removeFromParent();
  }
  function setAssets({moonMap,catalogue}={}) {
    if (disposed) { moonMap?.dispose();return; }
    if (moonMap) {
      if (moonTexture!==moonMap) moonTexture?.dispose();
      moonMap.colorSpace=THREE.SRGBColorSpace;
      moonMap.generateMipmaps=true;
      moonMap.minFilter=THREE.LinearMipmapLinearFilter;moonMap.magFilter=THREE.LinearFilter;
      // Match the twin's surface textures, bounded by the active renderer.
      moonMap.anisotropy=Math.min(tier==='low' ? 1 : 4,renderer.capabilities?.getMaxAnisotropy?.() || 1);
      moonMap.needsUpdate=true;
      moonTexture=moonMap;
      bodies.setMap(moonMap);cubeBodies.setMap(moonMap);
    }
    if (catalogue) { stars.setCatalogue(catalogue);cubeStars.setCatalogue(catalogue); }
    update({...previous,force:true});
  }
  function loadAssets(changed=()=>{}) {
    if (assetPromise) return assetPromise;
    const moonURL=new URL('./assets/moon_lroc_1k.jpg',import.meta.url).href;
    const starsURL=new URL('./assets/stars.json',import.meta.url).href;
    // A loader that throws at once must cost only its asset, never the twin's mount.
    const start=load=>{ try { return Promise.resolve(load()); } catch (error) { return Promise.reject(error); } };
    const moon=start(()=>new THREE.TextureLoader().loadAsync(moonURL)).then(map=>{
      setAssets({moonMap:map});if (!disposed) changed();
    });
    const catalogue=start(()=>fetch(starsURL)).then(response=>{
      if (!response.ok) throw new Error('Star catalogue '+response.status);
      return response.json();
    }).then(data=>{ if (!disposed) {setAssets({catalogue:data});changed();} });
    assetPromise=Promise.allSettled([moon,catalogue]);
    return assetPromise;
  }
  return {cube:target.texture,clearCube:clearTarget?.texture || target.texture,object,get environment(){return environmentTarget.texture;},update,setAssets,loadAssets,
    setEnabled(on) { bodies.setEnabled(on);stars.setEnabled(on); },
    frame(seconds) {
      stars.frame(seconds);
      if(disposed||!clouds)return false;
      frameSeconds=seconds;
      const fadeChanged=Math.abs(clouds.uniforms.cloudFade.value-cloudUniforms.cloudFade.value)>.05;
      const stateChanged=clouds.uniforms.cloudCoverage.value!==cloudUniforms.cloudCoverage.value||clouds.uniforms.cloudType.value!==cloudUniforms.cloudType.value;
      if(pendingFace===null&&(stateChanged||fadeChanged||(clouds.active&&seconds-lastCloudRefresh>=4))) {
        snapshotClouds();pendingFace=0;lastCloudRefresh=seconds;
      }
      if(pendingFace===null)return false;
      const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()],
        xr=renderer.xr.enabled,auto=renderer.autoClear,info={...renderer.info.render};
      try {
        renderer.xr.enabled=false;renderer.autoClear=true;
        camera.updateMatrixWorld();renderer.setRenderTarget(target,pendingFace);renderer.render(scene,camera.children[pendingFace]);
        if(++pendingFace===6) {
          pendingFace=null;target.texture.needsPMREMUpdate=true;
          environmentTarget=pmrem.fromCubemap(target.texture,environmentTarget);return true;
        }
        return false;
      } finally {renderer.setRenderTarget(...saved);renderer.xr.enabled=xr;renderer.autoClear=auto;Object.assign(renderer.info.render,info);}
    },
    horizon:dir=>new THREE.Color().setRGB(...sampleRadiance(dir,previous || {})),dispose};
}
