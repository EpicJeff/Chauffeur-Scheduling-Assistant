import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';
import { CLOUD_GLSL, CLOUD_TYPES, cloudDrift, createLightning, findLightningCell, sampleCloudDensity } from './clouds.js';
import { createNoiseVolumeSampler } from './cloud_noise.js';
import { createGPUCloudNoise } from './cloud_noise_gpu.js';

const vertexShader='varying vec2 vUv;void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}';
const clamp=(v,a=0,b=1)=>Number.isFinite(v)?Math.max(a,Math.min(b,v)):a;
const held=v=>v>=0?Math.min(v,4096):0;
export function compositeCloudPixel(background,cloud,depth) {
  if(depth<1-1e-7)return background.slice();
  const a=clamp(cloud[3]);return background.map((v,i)=>held(held(cloud[i])+held(v)*(1-a)));
}

// A toroidal high-pass ranked noise tile, generated once. Unlike a changing
// frame seed, this offset is fixed for every pixel of a still camera.
function blueNoise() {
  const n=32,values=new Float32Array(n*n),filtered=[];
  let seed=0x317acd;
  for(let i=0;i<values.length;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;values[i]=seed/4294967296;}
  for(let y=0;y<n;y++)for(let x=0;x<n;x++) {
    let average=0,weight=0;
    for(let dy=-2;dy<=2;dy++)for(let dx=-2;dx<=2;dx++) {
      const w=Math.exp(-(dx*dx+dy*dy)/2);average+=values[((y+dy+n)%n)*n+(x+dx+n)%n]*w;weight+=w;
    }
    filtered.push([values[y*n+x]-average/Math.max(weight,1e-6),y*n+x]);
  }
  filtered.sort((a,b)=>a[0]-b[0]);const data=new Uint8Array(n*n);
  filtered.forEach(([,i],rank)=>{data[i]=Math.floor(rank*256/(n*n));});
  const t=new THREE.DataTexture(data,n,n,THREE.RedFormat);t.wrapS=t.wrapT=THREE.RepeatWrapping;
  t.minFilter=t.magFilter=THREE.NearestFilter;t.generateMipmaps=false;t.needsUpdate=true;return t;
}

export function createCloudPass(renderer,{tier='low',noise,random=Math.random}={}) {
  const ownsNoise=!noise;noise ||= createGPUCloudNoise(renderer);
  const screen=tier!=='low',scale=tier==='medium'?.25:.5,budget={low:16,medium:40,high:64,max:96}[tier]||64;
  const uniforms={cloudBaseNoise:{value:noise.base},cloudDetailNoise:{value:noise.detail},cloudCoverage:{value:0},
    cloudType:{value:0},cloudFade:{value:noise.ready===undefined?1:0},cloudOffset:{value:new THREE.Vector3()},
    cloudSunRadiance:{value:new THREE.Vector3()},cloudMoonDir:{value:new THREE.Vector3(0,-1,0)},
    cloudMoonRadiance:{value:new THREE.Vector3()},cloudAmbientTop:{value:new THREE.Vector3(.1,.2,.4)},
    cloudAmbientBottom:{value:new THREE.Vector3(.03,.04,.02)},cloudLightning:{value:new THREE.Vector4()},cloudFog:{value:0},cloudFogColour:{value:new THREE.Vector3()}};
  const lightning=createLightning({random});
  // Read matches on every draw so changing the OS preference cancels a pulse
  // immediately, without a listener/timer to clean up on dispose.
  const motion=globalThis.window?.matchMedia?.('(prefers-reduced-motion: reduce)');
  let cpuNoise=null;
  const jitter=blueNoise();
  const marchUniforms={...uniforms,blueNoise:{value:jitter},sceneDepth:{value:null},clearSkyCube:{value:null},sunDir:{value:new THREE.Vector3(0,1,0)},
    inverseProjection:{value:new THREE.Matrix4()},cameraWorld:{value:new THREE.Matrix4()},
    marchSteps:{value:budget}};
  const material=new THREE.ShaderMaterial({uniforms:marchUniforms,vertexShader,depthTest:false,depthWrite:false,toneMapped:false,
    fragmentShader:`precision highp sampler3D;\n${CLOUD_GLSL}
      uniform sampler2D blueNoise,sceneDepth;
      uniform samplerCube clearSkyCube;
      uniform mat4 inverseProjection,cameraWorld;
      uniform vec3 sunDir;uniform float marchSteps;varying vec2 vUv;
      void main(){
        vec4 nearPoint=inverseProjection*vec4(vUv*2.0-1.0,-1.0,1.0);
        vec4 farPoint=inverseProjection*vec4(vUv*2.0-1.0,1.0,1.0);
        vec3 a=nearPoint.xyz/(abs(nearPoint.w)>1e-6?nearPoint.w:1e-6);
        vec3 b=farPoint.xyz/(abs(farPoint.w)>1e-6?farPoint.w:1e-6);
        vec3 rd=cloudUnit(mat3(cameraWorld)*(b-a));
        // cameraPosition is already metres: the twin generator converts feet.
        vec3 ro=(cameraWorld*vec4(a,1.0)).xyz;
        float jitter=texture2D(blueNoise,gl_FragCoord.xy/32.0).r;
        vec3 clearSky=textureCube(clearSkyCube,rd).rgb;
        gl_FragColor=marchClouds(ro,rd,marchSteps,jitter,sunDir,clearSky);
      }`});
  material.name='twin-cloud-march';
  const target=new THREE.WebGLRenderTarget(1,1,{type:THREE.HalfFloatType,depthBuffer:false,minFilter:THREE.LinearFilter,magFilter:THREE.LinearFilter});
  const compositeUniforms={cloudImage:{value:target.texture},sceneImage:{value:null},sceneDepth:{value:null},
    cloudSize:{value:new THREE.Vector2(1,1)},hasBackground:{value:1},cloudActive:{value:1}};
  const compositeMaterial=new THREE.ShaderMaterial({uniforms:compositeUniforms,vertexShader,toneMapped:false,
    depthTest:true,depthWrite:true,depthFunc:THREE.AlwaysDepth,
    fragmentShader:`uniform sampler2D cloudImage,sceneImage,sceneDepth;
      uniform vec2 cloudSize;uniform float hasBackground,cloudActive;varying vec2 vUv;
      float held(float v){return v>=0.0?min(v,4096.0):0.0;}
      vec3 safeRGB(vec3 v){return vec3(held(v.r),held(v.g),held(v.b));}
      void main(){
        float depth=texture2D(sceneDepth,vUv).r;gl_FragDepth=depth;
        vec3 background=hasBackground>0.5?safeRGB(texture2D(sceneImage,vUv).rgb):vec3(0.0);
        vec4 cloud=vec4(0.0);
        if(depth>=1.0-1e-7&&cloudActive>0.5){
          vec2 p=vUv*cloudSize-0.5,base=floor(p),f=fract(p);float total=0.0;
          vec4 fallback=texture2D(cloudImage,vUv);
          for(int y=0;y<2;y++)for(int x=0;x<2;x++){
            vec2 uv=(base+vec2(x,y)+0.5)/max(cloudSize,vec2(1.0));
            float tapDepth=texture2D(sceneDepth,uv).r;
            float w=(x==0?1.0-f.x:f.x)*(y==0?1.0-f.y:f.y);
            // Reject foreground taps when reconstructing a far-plane pixel.
            w*=tapDepth>=1.0-1e-7?1.0:0.0;
            cloud+=texture2D(cloudImage,uv)*w;total+=w;
          }
          // Every low-res pixel holds a cloud ray, even behind geometry. This
          // fallback prevents holes in sky gaps narrower than a march pixel.
          cloud=total>1e-6?cloud/max(total,1e-6):fallback;
        }
        float alpha=cloud.a>=0.0?clamp(cloud.a,0.0,1.0):0.0;
        gl_FragColor=vec4(safeRGB(safeRGB(cloud.rgb)+background*(1.0-alpha)),1.0);
      }`});
  compositeMaterial.name='twin-cloud-composite';
  const marchQuad=new FullScreenQuad(material),compositeQuad=new FullScreenQuad(compositeMaterial);
  // Capture the renderer's native compiler before twin_view wraps scene warmups.
  // Noise and screen programs warm asynchronously without holding the house.
  const compile=renderer.compileAsync?.bind(renderer),compileEye=new THREE.OrthographicCamera(-1,1,1,-1,0,1);
  let warmReady=!compile,warming=false,warmError=null;
  let disposed=false,seconds=null,readySince=null,state={coverage:0,type:'none',windMps:3,windToDeg:90},bearing=180;
  function savedDraw(draw) {
    const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()],auto=renderer.autoClear,xr=renderer.xr.enabled;
    try {renderer.xr.enabled=false;renderer.autoClear=false;return draw();}
    finally {renderer.setRenderTarget(...saved);renderer.autoClear=auto;renderer.xr.enabled=xr;}
  }
  const api={uniforms,material,compositeMaterial,target,screen,noise,
    get active(){return !disposed&&uniforms.cloudCoverage.value>0&&uniforms.cloudType.value>0&&uniforms.cloudFade.value>0;},
    get depthTexture(){return marchUniforms.sceneDepth.value;},
    get error(){return warmError||noise.error;},
    warm(destination=target) {
      noise.warm?.(destination);
      if(disposed||warming||warmReady||!screen)return;
      warming=true;
      savedDraw(()=>{
        renderer.setRenderTarget(destination);
        Promise.all([compile(marchQuad._mesh,compileEye),compile(compositeQuad._mesh,compileEye)])
          .then(()=>{warmReady=true;},error=>{warmError=error;});
      });
    },
    update(next={},light={}) {
      state={...state,...next};uniforms.cloudCoverage.value=clamp(state.coverage);uniforms.cloudType.value=CLOUD_TYPES[state.type]||0;
      const set=(name,value)=>{if(value?.isVector3)value=value.toArray();if(value?.every(Number.isFinite))uniforms[name].value.fromArray(value);};
      set('cloudSunRadiance',light.sunRadiance);set('cloudMoonDir',light.moonDir);set('cloudMoonRadiance',light.moonRadiance);
      set('cloudAmbientTop',light.ambientTop);set('cloudAmbientBottom',light.ambientBottom);
      uniforms.cloudFog.value=Number.isFinite(light.extinction)?Math.max(0,light.extinction):-Math.log(Math.max(1-clamp(light.fog),1e-10))/10000;
      set('cloudFogColour',light.fogColour);
      if(light.sunDir?.every(Number.isFinite))marchUniforms.sunDir.value.fromArray(light.sunDir).normalize();
      if(Number.isFinite(light.frontBearingDeg))bearing=light.frontBearingDeg;
    },
    flash(now,{enabled=true,centre=[0,0]}={}) {
      const pulse=lightning.frame(now,{enabled:!disposed&&enabled&&!motion?.matches&&state.lightning===true&&
        uniforms.cloudType.value===CLOUD_TYPES.cumulonimbus&&uniforms.cloudCoverage.value>0&&uniforms.cloudFade.value>=1,
        locate:()=>{
          cpuNoise ??= noise.base.image.data ? noise : {base:createNoiseVolumeSampler(noise.base.image.width),
            detail:createNoiseVolumeSampler(noise.detail.image.width,{detail:true})};
          const options={...cpuNoise,coverage:uniforms.cloudCoverage.value,type:'cumulonimbus',offset:uniforms.cloudOffset.value.toArray()};
          return findLightningCell(p=>sampleCloudDensity(p,options),centre,random);
        }});
      if(pulse.position)uniforms.cloudLightning.value.set(...pulse.position,pulse.strength);
      else uniforms.cloudLightning.value.set(0,0,0,0);
      return pulse.strength;
    },
    frame(now) {
      if(disposed||!Number.isFinite(now))return;
      noise.step?.(2);
      api.warm();
      const dt=seconds===null?0:Math.max(0,Math.min(1,now-seconds));seconds=now;
      if(noise.ready&&(!screen||warmReady)) {readySince ??= now;uniforms.cloudFade.value=clamp((now-readySince)/.75);}
      const drift=cloudDrift(state,dt),angle=(180-bearing)*Math.PI/180;
      const offset=uniforms.cloudOffset.value;
      offset.x+=Math.cos(angle)*drift.eastM+Math.sin(angle)*drift.northM;
      offset.z+=Math.sin(angle)*drift.eastM-Math.cos(angle)*drift.northM;
      // 144 km repeats the weather/base/detail tiles AND the 1.3 detail drift.
      offset.x=((offset.x+72000)%144000+144000)%144000-72000;
      offset.z=((offset.z+72000)%144000+144000)%144000-72000;
    },
    render(scene,camera,depthTexture) {
      if(!screen||!api.active)return target.texture;
      const size=renderer.getSize(new THREE.Vector2()).multiplyScalar(renderer.getPixelRatio());
      const w=Math.max(1,Math.ceil(size.x*scale)),h=Math.max(1,Math.ceil(size.y*scale));
      if(target.width!==w||target.height!==h)target.setSize(w,h);
      compositeUniforms.cloudSize.value.set(w,h);marchUniforms.sceneDepth.value=depthTexture;
      // Only this screen shader gains a sampler. The cube passes its already
      // evaluated atmosphere directly; no lit surface material is changed.
      marchUniforms.clearSkyCube.value=scene.background?.isCubeTexture?scene.background:null;
      camera.updateMatrixWorld();marchUniforms.inverseProjection.value.copy(camera.projectionMatrixInverse);
      marchUniforms.cameraWorld.value.copy(camera.matrixWorld);
      return savedDraw(()=>{renderer.setRenderTarget(target);marchQuad.render(renderer);return target.texture;});
    },
    composite(background,destination,depthTexture) {
      if(disposed)return;
      compositeUniforms.sceneImage.value=background;compositeUniforms.hasBackground.value=background?1:0;
      compositeUniforms.sceneDepth.value=depthTexture;compositeUniforms.cloudActive.value=api.active?1:0;
      savedDraw(()=>{renderer.setRenderTarget(destination);compositeQuad.render(renderer);});
    },
    dispose(){if(disposed)return;disposed=true;cpuNoise=null;uniforms.cloudLightning.value.set(0,0,0,0);target.dispose();jitter.dispose();material.dispose();compositeMaterial.dispose();
      marchQuad.dispose();compositeQuad.dispose();if(ownsNoise)noise.dispose();}};
  return api;
}
