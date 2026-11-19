import * as THREE from 'three';
import { FullScreenQuad } from 'three/addons/postprocessing/Pass.js';

// Exact integer hash, seeds, periods and channel layout of cloud_noise.js.
// The CPU generator remains the reference, never called by the viewer.
export const NOISE_GLSL = `
precision highp int;
uint noiseHash(ivec3 p, uint seed) {
  uint h=uint(p.x)*374761393u ^ uint(p.y)*668265263u ^ uint(p.z)*2147483647u ^ seed;
  h=(h ^ (h >> 13u))*1274126177u;
  return h ^ (h >> 16u);
}
ivec3 noiseWrap(ivec3 p,int period) { return (p%period+period)%period; }
vec3 noiseGradient(ivec3 p,int period) {
  const vec3 gradients[12]=vec3[12](vec3(1,1,0),vec3(-1,1,0),vec3(1,-1,0),vec3(-1,-1,0),
    vec3(1,0,1),vec3(-1,0,1),vec3(1,0,-1),vec3(-1,0,-1),
    vec3(0,1,1),vec3(0,-1,1),vec3(0,1,-1),vec3(0,-1,-1));
  return gradients[int(noiseHash(noiseWrap(p,period),17u)%12u)]*0.7071067811865476;
}
float noisePerlin(vec3 p,int period) {
  ivec3 cell=ivec3(floor(p));vec3 f=fract(p),u=f*f*f*(f*(f*6.0-15.0)+10.0);
  float result=0.0;
  for(int z=0;z<2;z++)for(int y=0;y<2;y++)for(int x=0;x<2;x++) {
    vec3 corner=vec3(x,y,z),w=mix(vec3(1.0)-u,u,corner);
    result+=dot(noiseGradient(cell+ivec3(x,y,z),period),f-corner)*w.x*w.y*w.z;
  }
  return result;
}
float noiseWorley(vec3 p,int period,uint seed) {
  ivec3 cell=ivec3(floor(p));vec3 f=fract(p);float nearest=3.0;
  // Visit the containing cell first and reject boxes beyond the current F1.
  for(int zi=0;zi<3;zi++)for(int yi=0;yi<3;yi++)for(int xi=0;xi<3;xi++) {
    ivec3 o=ivec3(xi==0?0:(xi==1?-1:1),yi==0?0:(yi==1?-1:1),zi==0?0:(zi==1?-1:1));
    vec3 bounds=max(max(vec3(o)-f,f-(vec3(o)+1.0)),vec3(0.0));
    if(dot(bounds,bounds)>=nearest) continue;
    ivec3 q=noiseWrap(cell+o,period);
    vec3 feature=vec3(float(noiseHash(q,seed+1013u)),float(noiseHash(q,seed+2026u)),float(noiseHash(q,seed+3039u)))/4294967296.0;
    vec3 delta=vec3(o)+feature-f;nearest=min(nearest,dot(delta,delta));
  }
  return clamp(sqrt(max(0.0,nearest)),0.0,1.0);
}
vec4 noiseVoxel(vec3 uv,bool detail) {
  vec3 cells=vec3(1.0-noiseWorley(uv*4.0,4,detail?71u:29u),
    1.0-noiseWorley(uv*8.0,8,detail?71u:29u),1.0-noiseWorley(uv*16.0,16,detail?71u:29u));
  float w=dot(cells,vec3(0.625,0.25,0.125)),shape=w;
  if(!detail) {
    float p=clamp(0.5+noisePerlin(uv*4.0,4)*0.625+noisePerlin(uv*8.0,8)*0.25+noisePerlin(uv*16.0,16)*0.125,0.0,1.0);
    shape=clamp((p+1.0-w)/max(2.0-w,1e-6),0.0,1.0);
  }
  return vec4(shape,cells);
}`;

// Independent JS port of the GLSL, for environments without a GL context.
// Compare quantized results against generateNoiseVolume, not against itself.
export function noiseVoxelGLSLReference(uv,detail=false) {
  const hash=(p,seed)=>{let h=Math.imul(p[0],374761393)^Math.imul(p[1],668265263)^Math.imul(p[2],2147483647)^seed;
    h=Math.imul(h^(h>>>13),1274126177);return (h^(h>>>16))>>>0;};
  const wrap=(p,n)=>p.map(v=>((v%n)+n)%n),dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const gradients=[[1,1,0],[-1,1,0],[1,-1,0],[-1,-1,0],[1,0,1],[-1,0,1],
    [1,0,-1],[-1,0,-1],[0,1,1],[0,-1,1],[0,1,-1],[0,-1,-1]];
  function octave(period) {
    const p=uv.map(v=>v*period),cell=p.map(Math.floor),f=p.map((v,i)=>v-cell[i]);
    const u=f.map(v=>v*v*v*(v*(v*6-15)+10));let gradient=0,nearest=3;
    for(let z=0;z<2;z++)for(let y=0;y<2;y++)for(let x=0;x<2;x++) {
      const o=[x,y,z],g=gradients[hash(wrap(cell.map((v,i)=>v+o[i]),period),17)%12].map(v=>Math.fround(v*Math.SQRT1_2));
      gradient+=dot(g,f.map((v,i)=>v-o[i]))*o.reduce((w,v,i)=>w*(v?u[i]:1-u[i]),1);
    }
    for(const z of [0,-1,1])for(const y of [0,-1,1])for(const x of [0,-1,1]) {
      const o=[x,y,z],bounds=o.map((v,i)=>Math.max(v-f[i],f[i]-(v+1),0));
      if(dot(bounds,bounds)>=nearest)continue;
      const q=wrap(cell.map((v,i)=>v+o[i]),period),seed=detail?71:29;
      const delta=o.map((v,i)=>v+Math.fround(hash(q,seed+1013*(i+1))/4294967296)-f[i]);
      nearest=Math.min(nearest,dot(delta,delta));
    }
    return [gradient,1-Math.min(1,Math.sqrt(Math.max(0,nearest)))];
  }
  const octaves=[4,8,16].map(octave),weights=[.625,.25,.125];
  const w=octaves.reduce((s,v,i)=>s+v[1]*weights[i],0),p=Math.max(0,Math.min(1,.5+octaves.reduce((s,v,i)=>s+v[0]*weights[i],0)));
  return [detail?w:Math.max(0,Math.min(1,(p+1-w)/Math.max(2-w,1e-6))),...octaves.map(v=>v[1])];
}

export function createGPUCloudNoise(renderer,{size=128,detail=32}={}) {
  if(![size,detail].every(n=>Number.isInteger(n)&&n>=2&&n<=128))throw new RangeError('Cloud texture size must be 2..128');
  const make=(n,name)=>{
    const t=new THREE.WebGL3DRenderTarget(n,n,n,{depthBuffer:false,type:THREE.UnsignedByteType,format:THREE.RGBAFormat,
      minFilter:THREE.LinearFilter,magFilter:THREE.LinearFilter,wrapS:THREE.RepeatWrapping,wrapT:THREE.RepeatWrapping,
      generateMipmaps:false});
    t.texture.wrapR=THREE.RepeatWrapping;t.texture.name=name;t.texture.unpackAlignment=1;return t;
  };
  const base=make(size,'twin-cloud-base'),erosion=make(detail,'twin-cloud-detail');
  const uniforms={volumeSize:{value:size},slice:{value:0},detailVolume:{value:0}};
  const material=new THREE.ShaderMaterial({uniforms,depthTest:false,depthWrite:false,toneMapped:false,
    vertexShader:'void main(){gl_Position=vec4(position.xy,0.0,1.0);}',
    fragmentShader:NOISE_GLSL+`\nuniform float volumeSize,slice,detailVolume;
      void main(){gl_FragColor=noiseVoxel(vec3(gl_FragCoord.xy,slice+0.5)/max(volumeSize,1.0),detailVolume>0.5);}`});
  material.name='twin-cloud-noise';
  const quad=new FullScreenQuad(material);
  const compile=renderer.compileAsync?.bind(renderer),eye=new THREE.OrthographicCamera(-1,1,1,-1,0,1);
  let cursor=0,disposed=false,compiling=false,compiled=!renderer.compileAsync,error=null;
  function warm(destination=base) {
    if(disposed||compiled||compiling||error)return;
    const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()];
    try {
      compiling=true;renderer.setRenderTarget(destination,0);
      Promise.resolve(compile(quad._mesh,eye)).then(()=>{compiled=true;},e=>{error=e;});
    } catch(e) {error=e;}
    finally {renderer.setRenderTarget(...saved);}
  }
  return {base:base.texture,detail:erosion.texture,get ready(){return cursor===size+detail&&!error;},get error(){return error;},
    warm,
    step(budget=2) {
      if(disposed||error||cursor>=size+detail)return 0;
      const saved=[renderer.getRenderTarget(),renderer.getActiveCubeFace(),renderer.getActiveMipmapLevel()],
        xr=renderer.xr.enabled,auto=renderer.autoClear,info={...renderer.info.render};
      try {
        renderer.xr.enabled=false;renderer.autoClear=true;
        if(!compiled) {
          warm();
          return 0;
        }
        let count=0;
        for(;count<Math.max(1,Math.min(4,budget))&&cursor<size+detail;count++,cursor++) {
          const second=cursor>=size,target=second?erosion:base;
          uniforms.volumeSize.value=target.width;uniforms.slice.value=second?cursor-size:cursor;uniforms.detailVolume.value=second?1:0;
          // r187 uses activeCubeFace as the 3D texture's framebuffer layer.
          renderer.setRenderTarget(target,uniforms.slice.value);quad.render(renderer);
        }
        return count;
      } catch(e) {error=e;return 0;}
      finally {renderer.setRenderTarget(...saved);renderer.xr.enabled=xr;renderer.autoClear=auto;Object.assign(renderer.info.render,info);}
    },
    dispose(){if(disposed)return;disposed=true;base.dispose();erosion.dispose();material.dispose();quad.dispose();}};
}
