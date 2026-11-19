"""Cloud aerial perspective and thick-layer lighting; execute shader scalar math offline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {CLOUD_GLSL,createCloudNoise,sampleCloudDensity}=await import(file('static/twin/sky/clouds.js'));
const {sampleRadiance,sampleSkyIrradiance,transmittance,createSky}=await import(file('static/twin/sky/atmosphere.js'));
const {createCloudPass,compositeCloudPixel}=await import(file('static/twin/sky/cloud_pass.js'));
// These functions contain scalar arithmetic only. Execute their actual GLSL
// bodies rather than a second implementation of the quantities under test.
const clamp=(x,a,b)=>Math.max(a,Math.min(b,x)),mix=(a,b,t)=>a*(1-t)+b*t;
const smoothstep=(a,b,x)=>{const t=clamp((x-a)/(b-a),0,1);return t*t*(3-2*t);};
function shaderFunction(name,dependencies={}) {
  const match=CLOUD_GLSL.match(new RegExp('float '+name+'\\(([^)]*)\\) \\{([\\s\\S]*?)\\n\\}'));
  assert.ok(match,'shader function '+name);
  const args=match[1].replace(/\bfloat\s+/g,'');
  const body=match[2].replace(/\b(?:float|int)\s+/g,'let ');
  const scope={...Math,exp:Math.exp,pow:Math.pow,max:Math.max,min:Math.min,floor:Math.floor,fract:x=>x-Math.floor(x),
    clamp,mix,smoothstep,...dependencies};
  return new Function(...Object.keys(scope),'return function('+args+'){'+body+'}')( ...Object.values(scope));
}
let air,ambient,scatter,hg,distanceAt,detailWeight,jitterAt;
await test('shader helpers execute: perspective, hemispheric ambient, optical-depth scattering and grazing sampling',()=>{
  air=shaderFunction('cloudAirWeight');ambient=shaderFunction('cloudAmbientChannel');
  hg=shaderFunction('cloudHG');scatter=shaderFunction('cloudScatterDepth',{cloudHG:hg});
  distanceAt=shaderFunction('cloudSampleDistance');detailWeight=shaderFunction('cloudDetailWeight');
  jitterAt=shaderFunction('cloudStepJitter');
});
await test('80 km clouds converge within 4.1% of clear directional radiance; 2 km clouds retain contrast',()=>{
  for(const altitude of [70,4,-6,-30])for(const azimuth of [0,Math.PI/2,Math.PI]) {
    const a=altitude*Math.PI/180,state={sunDir:[Math.cos(a),Math.sin(a),0]};
    const sky=sampleRadiance([Math.cos(azimuth),.01,Math.sin(azimuth)],state);
    for(const cloud of [[0,0,0],[1,.2,.05],[10,3,1]])for(const opacity of [.25,1]) {
      const near=cloud.map((v,i)=>mix(v,sky[i],air(2000))*opacity);
      const far=cloud.map((v,i)=>mix(v,sky[i],air(80000))*opacity);
      const n=compositeCloudPixel(sky,[...near,opacity],1),f=compositeCloudPixel(sky,[...far,opacity],1);
      cloud.forEach((v,i)=>{
        const contrast=Math.abs(v-sky[i])*opacity;
        assert.ok(Math.abs(f[i]-sky[i])<=contrast*.041+1e-10);
        assert.ok(Math.abs(n[i]-sky[i])>=contrast*.92-1e-10);
      });
    }
  }
  console.log('Air contrast retained: 2 km '+(1-air(2000))+'; 80 km '+(1-air(80000)));
});
await test('actual hemispheric irradiance lights thick overcast and rain at noon, golden hour and dusk',()=>{
  assert.equal(typeof sampleSkyIrradiance,'function');
  for(const altitude of [70,4,-6,-30])for(const overcast of [.85,1]) {
    const a=altitude*Math.PI/180,state={sunDir:[Math.cos(a),Math.sin(a),0],overcast};
    const {top,bottom}=sampleSkyIrradiance(state);
    for(const h of [0,.1,.5,.9,1])for(const depth of [0,1,10,100,1000])for(const mu of [-1,0,1]) {
      const light=top.map((v,i)=>ambient(bottom[i],v,h)+scatter(depth,mu));
      light.forEach((v,i)=>{
        assert.ok(Number.isFinite(v)&&v>=0);
        assert.ok(v>=.3*(top[i]+bottom[i])*.5,'thick layer stays above a floor proportional to sky irradiance');
      });
    }
    console.log('sun '+altitude+' cover '+overcast+' irradiance/pi top '+top+' bottom '+bottom+
      ' underside '+top.map((v,i)=>ambient(bottom[i],v,0)));
    if(altitude===4)assert.ok(top[0]>sampleRadiance([0,1,0],state)[0]*1.5,'hemisphere includes bright sunset horizon');
  }
  const day=sampleSkyIrradiance({sunDir:[0,1,0]}),night=sampleSkyIrradiance({sunDir:[0,-1,0]});
  assert.ok(night.top.reduce((a,b)=>a+b)<day.top.reduce((a,b)=>a+b)*.1);
  assert.ok(ambient(.1,1,1)>ambient(.1,1,0),'cloud tops stay brighter than undersides');
  assert.ok(scatter(100,0)>0,'multiple scattering retains optically thick illumination');
  assert.ok(scatter(1,0)>scatter(100,0),'edges are brighter than thick interiors');
});
await test('distance steps partition the ray, decorrelate depths and suppress unresolved erosion',()=>{
  for(const [start,end] of [[1500,4000],[20000,80000],[100000,225000]])for(const steps of [16,40,64,96]) {
    let sum=0,last=start;const offsets=[];
    for(let j=0;j<steps;j++) {
      const a=distanceAt(start,end,j/steps),b=distanceAt(start,end,(j+1)/steps);
      assert.ok(a>=last-1e-9&&b>a);sum+=b-a;last=b;
      const jitter=jitterAt(.37,j);assert.ok(jitter>=0&&jitter<1);assert.equal(jitter,jitterAt(.37,j));offsets.push(jitter);
    }
    assert.ok(Math.abs(sum-(end-start))<1e-8);assert.equal(new Set(offsets).size,steps);
    assert.ok(distanceAt(start,end,1/steps)-start<(end-start)/steps);
  }
  assert.equal(detailWeight(2000,100),1);assert.equal(detailWeight(40000,100),0);
  assert.equal(detailWeight(2000,2000),0);
});
await test('screen receives the clear directional cube and real hemisphere uniforms without material changes',()=>{
  const r=new Renderer(),noise=createCloudNoise({size:8,detail:4}),c=createCloudPass(r,{tier:'high',noise});
  const scene=new THREE.Scene(),cube=new THREE.WebGLCubeRenderTarget(8),camera=new THREE.PerspectiveCamera();
  scene.background=cube.texture;
  const version=c.material.version,key=c.material.customProgramCacheKey();
  for(const altitude of [70,4,-6,-30])for(const coverage of [0,.4,.85,1]) {
    const a=altitude*Math.PI/180,light=sampleSkyIrradiance({sunDir:[Math.cos(a),Math.sin(a),0]});
    c.update({coverage,type:'stratocumulus'},{ambientTop:light.top,ambientBottom:light.bottom});
    c.render(scene,camera,null);
    assert.deepEqual(c.uniforms.cloudAmbientTop.value.toArray(),light.top);
    assert.equal(c.material.version,version);assert.equal(c.material.customProgramCacheKey(),key);
    if(coverage)assert.equal(c.material.uniforms.clearSkyCube.value,cube.texture);
  }
  c.dispose();noise.dispose();cube.dispose();
});
await test('clear cube supplies atmosphere alone; cloudy reflections retain celestial meshes',()=>{
  const r=new Renderer(),noise=createCloudNoise({size:8,detail:4}),c=createCloudPass(r,{tier:'high',noise});
  const draw=r.render,seen=[];
  r.render=function(s,camera){
    if(s.name==='twin-atmosphere')seen.push({texture:this.target.texture,celestial:s.children.slice(1).map(o=>o.visible)});
    draw.call(this,s,camera);
  };
  const sky=createSky(r,{tier:'high',clouds:c});
  assert.ok(seen.filter(s=>s.texture===sky.clearCube).length===6);
  assert.ok(seen.filter(s=>s.texture===sky.clearCube).every(s=>s.celestial.every(v=>v===false)));
  assert.ok(seen.filter(s=>s.texture===sky.cube).every(s=>s.celestial.every(v=>v===true)));
  sky.dispose();c.dispose();noise.dispose();
});
await test('integrated thick-layer reference march is finite and bounded by measured sky illumination',()=>{
  // CPU reference of the shared march, using the real density texture sampling
  // plus the shader's executed scalar helpers. No GPU/pixel proof is claimed.
  const noise=createCloudNoise({size:32,detail:16}),earth=6360000;
  const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0),along=(p,d,t)=>p.map((v,i)=>v+d[i]*t);
  const height=p=>Math.hypot(p[0],p[1]+earth,p[2])-earth;
  function sphere(p,d,r) {
    const q=[p[0],p[1]+earth,p[2]],b=dot(q,d),radius=Math.hypot(...q),h=b*b-(radius-r)*(radius+r);
    return h<0?[-1,-1]:[-b-Math.sqrt(h),-b+Math.sqrt(h)];
  }
  function segment(p,d,layer) {
    const outer=sphere(p,d,earth+layer[1]);if(outer[1]<=0)return [0,0];
    let start=Math.max(0,outer[0]),end=Math.min(outer[1],250000);
    const inner=sphere(p,d,earth+layer[0]);
    if(height(p)<layer[0])start=Math.max(start,inner[1]);else if(inner[0]>0)end=Math.min(end,inner[0]);
    const ground=sphere(p,d,earth);if(ground[0]>0)end=Math.min(end,ground[0]);
    return end>start?[start,end]:[0,0];
  }
  function march(rd,state,type,coverage,steps=64) {
    const layer=type==='nimbostratus'?[500,1500]:[1500,4000],ro=[0,2,0],sun=state.sunDir;
    const bounds=segment(ro,rd,layer),sky=sampleRadiance(rd,state),hemi=sampleSkyIrradiance(state);
    const direct=transmittance([sun[0],Math.max(0,sun[1]),sun[2]]).map(v=>v*10);
    const density=(p,detailWeight=1)=>sampleCloudDensity(p,{...noise,type,coverage,detailWeight});
    const rgb=[0,0,0],contrast=[0,0,0];let transmission=1;
    for(let j=0;j<steps&&transmission>=.005;j++) {
      const a=distanceAt(...bounds,j/steps),b=distanceAt(...bounds,(j+1)/steps),ds=b-a;
      const distance=mix(a,b,jitterAt(.37,j)),p=along(ro,rd,distance),d=density(p,detailWeight(distance,ds));
      if(d<=0)continue;
      const stepT=Math.exp(-d*ds*.0025),h=clamp((height(p)-layer[0])/(layer[1]-layer[0]),0,1);
      let depth=1e6;
      if(sphere(p,sun,earth)[0]<=0) {
        depth=0;const [start,end]=segment(p,sun,layer);
        for(let k=0;k<6;k++) {
          const a=mix(start,end,(k/6)**2),b=mix(start,end,((k+1)/6)**2);
          depth+=density(along(p,sun,(a+b)*.5))*(b-a)*.0025;
        }
      }
      for(let i=0;i<3;i++) {
        const light=ambient(hemi.bottom[i],hemi.top[i],h)+direct[i]*scatter(depth,dot(rd,sun));
        rgb[i]+=transmission*(1-stepT)*mix(light,sky[i],air(distance));
        contrast[i]+=transmission*(1-stepT)*Math.abs(light-sky[i]);
      }
      transmission*=stepT;
    }
    return {rgb,opacity:1-transmission,hemi,sky,contrast,start:bounds[0]};
  }
  for(const altitude of [70,4,-6,-30])for(const [type,coverage] of [['stratocumulus',.85],['nimbostratus',1]]) {
    const a=altitude*Math.PI/180,state={sunDir:[Math.cos(a),Math.sin(a),0],overcast:coverage};
    for(const elevation of [90,30,4,.1,-.1]) {
      const e=elevation*Math.PI/180,result=march([Math.cos(e),Math.sin(e),0],state,type,coverage);
      assert.ok([...result.rgb,result.opacity].every(v=>Number.isFinite(v)&&v>=0));
      assert.ok(result.opacity<=1&&result.rgb.every(v=>v<=4096));
      if(elevation===4) {
        assert.ok(result.opacity>.95,'actual thick layer is opaque');
        result.rgb.forEach((v,i)=>assert.ok(v>.3*(result.hemi.top[i]+result.hemi.bottom[i])*.5*result.opacity));
        console.log('Integrated '+type+' sun '+altitude+' radiance '+result.rgb+' opacity '+result.opacity);
      }
      if(elevation===.1)result.rgb.forEach((v,i)=>{
        // Cumulus starts >100 km away; low rain starts >65 km away.
        const composite=v+result.sky[i]*(1-result.opacity);
        assert.ok(result.start>60000);
        assert.ok(Math.abs(composite-result.sky[i])<=result.contrast[i]*Math.exp(-result.start/25000)+1e-10,
          'grazing-cloud contrast is bounded by air extinction to the layer');
      });
    }
  }
  noise.dispose();
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(out)
    sys.exit(code if code is not None else 1)
