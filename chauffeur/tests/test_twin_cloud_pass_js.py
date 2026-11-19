"""Cloud pipeline, real r187 resources/program keys and GLSL reference math; no GL/browser."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE=await import('three');
registerHooks({load(url,ctx,next){
  if(url.endsWith('three.module.js?cloud-keys'))return {format:'module',shortCircuit:true,source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
  return next(url,ctx);
}});
const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?cloud-keys');
const programCaches=new WeakMap();
function programKey(renderer,scene,object) {
  renderer.state={buffers:{depth:{getReversed:()=>false}}};
  if(!programCaches.has(renderer))programCaches.set(renderer,WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},{},{numPlanes:0,numIntersection:0}));
  const cache=programCaches.get(renderer);
  const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi','sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
  lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
  return cache.getProgramCacheKey(cache.getParameters(object.material,lights,[],scene,object,[]));
}
const {createCloudPass, compositeCloudPixel}=await import(file('static/twin/sky/cloud_pass.js'));
const {createGPUCloudNoise, noiseVoxelGLSLReference}=await import(file('static/twin/sky/cloud_noise_gpu.js'));
const {generateNoiseVolume}=await import(file('static/twin/sky/cloud_noise.js'));
const {createCloudNoise}=await import(file('static/twin/sky/clouds.js'));
const {createSky}=await import(file('static/twin/sky/atmosphere.js'));
const {createPost}=await import(file('static/twin/post.js'));
const {createBodies}=await import(file('static/twin/sky/bodies.js'));
await test('independent GLSL noise reference agrees with CPU RGBA8 volumes to one byte',()=>{
  for(const detail of [false,true])for(const size of [8,32]) {
    const data=generateNoiseVolume(size,{detail});
    for(const [x,y,z] of [[0,0,0],[size-1,size-1,size-1],[1,3,5],[size-2,2,3]]) {
      const voxel=noiseVoxelGLSLReference([(x+.5)/size,(y+.5)/size,(z+.5)/size],detail);
      const i=((z*size+y)*size+x)*4;
      voxel.forEach((n,c)=>assert.ok(Math.abs(Math.round(n*255)-data[i+c])<=1,`${detail} ${size} ${c}`));
    }
  }
});
await test('GPU volumes allocate without drawing or CPU generation; slices are bounded, state restored, disposal idempotent',()=>{
  const r=new Renderer(),saved=new THREE.WebGLRenderTarget(4,4);r.setRenderTarget(saved,3,2);r.xr.enabled=true;r.autoClear=false;
  const calls=[],draw=r.render;r.render=function(s,c){calls.push([this.target,this.face,s.material]);draw.call(this,s,c);};
  const n=createGPUCloudNoise(r,{size:8,detail:4});assert.equal(calls.length,0);assert.equal(n.ready,false);
  assert.ok(n.base.isData3DTexture&&n.base.isRenderTargetTexture);assert.equal(n.base.image.data,null);
  for(let i=0;i<6;i++) {n.step(2);assert.equal(calls.length,(i+1)*2);}
  assert.equal(n.ready,true);assert.equal(new Set(calls.map(([t,z])=>t.texture.uuid+':'+z)).size,12);
  assert.equal(r.target,saved);assert.equal(r.face,3);assert.equal(r.mip,2);assert.equal(r.xr.enabled,true);assert.equal(r.autoClear,false);
  n.step(2);assert.equal(calls.length,12);
  const freed=[];for(const t of new Set(calls.map(c=>c[0])))t.addEventListener('dispose',()=>freed.push(t));
  n.dispose();n.dispose();assert.equal(freed.length,2);saved.dispose();
});
await test('native compiler warms every cloud program before first weather; mount never awaits compilation or noise',async()=>{
  const r=new Renderer(),pending=[],compiled=[];let draws=0;
  r.compileAsync=(mesh)=>{compiled.push(mesh.material.name);return new Promise(resolve=>pending.push(resolve));};
  const draw=r.render;r.render=function(s,c){draws++;draw.call(this,s,c);};
  const noise=createGPUCloudNoise(r,{size:4,detail:2}),cloud=createCloudPass(r,{tier:'high',noise});
  cloud.warm();assert.deepEqual(compiled,['twin-cloud-noise','twin-cloud-march','twin-cloud-composite']);
  cloud.update({coverage:1,type:'nimbostratus'});cloud.frame(0);assert.equal(draws,0);assert.equal(cloud.active,false);
  pending.forEach(resolve=>resolve());await Promise.resolve();await Promise.resolve();
  for(let i=1;i<=4;i++)cloud.frame(i*.02);
  assert.equal(noise.ready,true);assert.equal(compiled.length,3);assert.equal(draws,6);
  cloud.frame(1);assert.equal(cloud.uniforms.cloudFade.value,1);
  cloud.dispose();noise.dispose();
});
await test('clear and geometry pixels are unchanged, cloud pixels agree across output paths',()=>{
  const bg=[.1,.4,1],cloud=[.2,.15,.1,.75];
  assert.deepEqual(compositeCloudPixel(bg,cloud,.5),bg);
  assert.deepEqual(compositeCloudPixel(bg,[0,0,0,0],1),bg);
  assert.deepEqual(compositeCloudPixel(bg,cloud,1),[.225,.25,.35]);
  for(const d of [0,.99,1-1e-6])assert.deepEqual(compositeCloudPixel(bg,cloud,d),bg);
  assert.ok(compositeCloudPixel([NaN,Infinity,-1],[NaN,0,0,1],1).every(Number.isFinite));
});
await test('screen march uses tier resolution, beauty depth and fixed uniforms without changing programs',()=>{
  const noise=createCloudNoise({size:8,detail:4});
  for(const tier of ['medium','high','max']) {
    const r=new Renderer();r.setSize(1920,1080);const cloud=createCloudPass(r,{tier,noise});
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(38,16/9,.1,1000),depth=new THREE.DepthTexture(1920,1080);
    const calls=[],draw=r.render;r.render=function(s,c){calls.push([s.material,this.target]);draw.call(this,s,c);};
    const object=new THREE.Mesh(new THREE.PlaneGeometry(2,2),cloud.material);
    const key=programKey(r,scene,object),version=cloud.material.version;
    for(const coverage of [0,.4,1])for(const y of [1,0,-.1]) {
      cloud.update({coverage,type:coverage?'cumulus':'none',windMps:3,windToDeg:90},{sunDir:[1,y,0],sunRadiance:[1,1,1]});
      cloud.frame(2);cloud.render(scene,camera,depth);
      assert.equal(programKey(r,scene,object),key);assert.equal(cloud.material.version,version);
      assert.equal(cloud.material.uniforms.cloudCoverage.value,coverage);
      if(coverage>0)assert.equal(cloud.material.uniforms.sceneDepth.value,depth);
    }
    assert.equal(cloud.target.width,tier==='medium'?480:960);assert.equal(cloud.target.height,tier==='medium'?270:540);
    assert.ok(cloud.material.fragmentShader.includes('marchClouds('));assert.ok(cloud.material.fragmentShader.includes('sceneDepth'));
    const stable=cloud.material.uniforms.blueNoise.value.image.data.slice();cloud.frame(2);
    assert.deepEqual(cloud.material.uniforms.blueNoise.value.image.data,stable);
    const before=calls.length;cloud.update({coverage:0,type:'none'});cloud.render(scene,camera,depth);assert.equal(calls.length,before,'clear skips the march');
    cloud.dispose();cloud.dispose();depth.dispose();object.geometry.dispose();
  }
  noise.dispose();
});
await test('composer composites after beauty/AO and before bloom/output using beauty depth, same plain linear composite',()=>{
  const r=new Renderer();r.setSize(80,60);const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
  const noise=createCloudNoise({size:8,detail:4}),cloud=createCloudPass(r,{tier:'high',noise});
  cloud.update({coverage:1,type:'nimbostratus'});cloud.frame(1);
  const post=createPost(r,scene,camera,{clouds:cloud});
  assert.deepEqual(post.info().passes,['RenderPass','GTAOPass','CloudCompositePass','LightShaftPass','UnrealBloomPass','OutputPass']);
  const calls=[],draw=r.render;r.render=function(s,c){calls.push([s.material?.name||s.name,this.target]);draw.call(this,s,c);};
  post.render();assert.ok(calls.some(([name])=>name==='twin-cloud-composite'));
  assert.equal(cloud.depthTexture.type,THREE.FloatType);assert.equal(cloud.depthTexture.format,THREE.RedFormat);
  assert.notEqual(cloud.depthTexture,post.occlusionDepth);
  const first=cloud.compositeMaterial;cloud.composite(null,null,cloud.depthTexture);
  assert.equal(cloud.compositeMaterial,first,'plain linear targets use the identical shader');
  post.dispose();cloud.dispose();noise.dispose();
});
await test('cloud cube uses same march, clear cube stays cloud-free, drift amortizes six faces with fixed PMREM',()=>{
  const r=new Renderer(),noise=createCloudNoise({size:8,detail:4}),cloud=createCloudPass(r,{tier:'high',noise});
  cloud.update({coverage:1,type:'nimbostratus',windMps:3,windToDeg:90});cloud.frame(1);
  const draws=[],draw=r.render;r.render=function(s,c){draws.push([s,this.target,s.children?.[0]?.material?.uniforms.cloudViewEnabled?.value,s.children?.[0]?.material?.uniforms.cloudCoverage?.value]);draw.call(this,s,c);};
  const sky=createSky(r,{tier:'high',clouds:cloud}),cube=sky.cube,env=sky.environment,clear=sky.clearCube;
  assert.notEqual(cube,clear);assert.ok(draws.some(([s,t,on])=>s.name==='twin-atmosphere'&&t.texture===clear&&on===0));
  const mesh=draws.find(([s])=>s.name==='twin-atmosphere')[0].children[0],key=mesh.material.customProgramCacheKey();
  assert.ok(mesh.material.fragmentShader.includes('marchClouds('));
  const before=draws.length;for(let i=0;i<7;i++)sky.frame(5+i*.016);
  const cloudy=draws.slice(before).filter(([s,t,on])=>s.name==='twin-atmosphere'&&t.texture===cube&&on===1);
  assert.equal(cloudy.length,6);assert.equal(sky.environment,env);assert.equal(sky.cube,cube);
  assert.equal(mesh.material.customProgramCacheKey(),key);const count=draws.length;sky.frame(6);assert.equal(draws.length,count);
  sky.update({sunDir:[0,1,0],force:true});sky.frame(7); // Interrupt a partially refreshed cloudy cube.
  cloud.update({coverage:0,type:'none'});const clearStart=draws.length;
  sky.update({sunDir:[0,1,0],force:true});
  const cleared=draws.slice(clearStart).filter(([s,t])=>s.name==='twin-atmosphere'&&t.texture===cube);
  assert.equal(cleared.length,6);assert.ok(cleared.every(([,t,on,coverage])=>coverage===0),'zero coverage clears every cube face and cancels stale drift');
  sky.dispose();cloud.dispose();noise.dispose();
});
await test('disc transmittance scales visible strength without the retired scalar weather dimmer',()=>{
  const b=createBodies();
  b.update({sunDir:[0,1,0],overcast:1,cloudTransmittance:()=>.2});
  assert.equal(b.object.children[0].material.uniforms.strength.value,.2);
  b.update({sunDir:[0,1,0],overcast:1,cloudTransmittance:()=>1});
  assert.equal(b.object.children[0].material.uniforms.strength.value,1);b.dispose();
});
await test('transparent water/glass draw over clouds, opaque viewing copies stay in beauty, layers and state restore on failures',()=>{
  const r=new Renderer();r.setSize(80,60);const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
  const noise=createCloudNoise({size:8,detail:4}),cloud=createCloudPass(r,{tier:'high',noise});
  cloud.update({coverage:1,type:'nimbostratus'});
  const solid=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial({transparent:true}));solid.material.userData.viewingOpaque=true;
  const glass=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshPhysicalMaterial({transparent:true,depthWrite:false}));
  const star=new THREE.Mesh(new THREE.PlaneGeometry(),new THREE.MeshBasicMaterial({transparent:true,depthWrite:false}));star.name='sky-star-test';
  scene.add(solid,glass,star);const post=createPost(r,scene,camera,{clouds:cloud});
  const draw=r.render,calls=[];let fail=false;
  r.render=function(s,c){
    if(s===scene&&!s.overrideMaterial) {
      calls.push([solid.layers.test(camera.layers),glass.layers.test(camera.layers),star.layers.test(camera.layers)]);
      if(fail&&glass.layers.test(camera.layers))throw Error('transparent draw');
    }
    return draw.call(this,s,c);
  };
  const masks=scene.children.map(o=>o.layers.mask),background=new THREE.CubeTexture();scene.background=background;
  post.render();assert.deepEqual(calls,[[true,false,true],[false,true,false]]);
  assert.deepEqual(scene.children.map(o=>o.layers.mask),masks);assert.equal(scene.background,background);
  fail=true;assert.throws(()=>post.render(),/transparent draw/);
  assert.deepEqual(scene.children.map(o=>o.layers.mask),masks);assert.equal(scene.background,background);assert.equal(r.target,null);
  post.dispose();cloud.dispose();noise.dispose();background.dispose();
  for(const o of scene.children){o.material.dispose();o.geometry.dispose();}
});
await test('real mount never constructs CPU volumes; live weather/wind reach uniforms, noise fades after frames, editor stays clear',async()=>{
  const {mountTwin}=await import(file('static/twin/twin_view.js'));
  const oldLoop=Renderer.prototype.setAnimationLoop,oldNow=performance.now;let now=0;
  performance.now=()=>now;Renderer.prototype.setAnimationLoop=function(fn){this.cloudTick=fn;};
  try {
    for(const editor of [false,true]) {
      const host=new Element();if(editor)host.className='editor-shell';
      const v=await mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'medium',bake:false});
      try {
        assert.equal(v.clouds.noise.base.image.data,null);assert.equal(v.clouds.uniforms.cloudFade.value,0);
        let weather={state:'rainy',attributes:{cloud_coverage:100,wind_speed:10,wind_speed_unit:'m/s',wind_bearing:270}};
        v.live={peek:()=>({'weather.local':weather}),stale:()=>false,stop:()=>{},draw:()=>{}};v.render();
        assert.equal(v.clouds.uniforms.cloudCoverage.value,editor?0:1);
        for(let frame=0;frame<140;frame++){now+=17;v.renderer3.cloudTick();}
        assert.equal(v.clouds.noise.ready,true);assert.equal(v.clouds.uniforms.cloudFade.value,1);
        const offset=v.clouds.uniforms.cloudOffset.value.toArray();assert.ok(offset.every(Number.isFinite));
        weather={state:'cloudy',attributes:{cloud_coverage:100,wind_speed:10,wind_speed_unit:'m/s',wind_bearing:0}};v.render();
        assert.equal(v.clouds.uniforms.cloudType.value,editor?0:2,'type changes even at equal coverage');
        v.live.stale=()=>true;v.render();assert.equal(v.clouds.uniforms.cloudCoverage.value,0);
        assert.equal(v.clouds.noise.base.image.data,null);
      } finally {v.dispose();}
    }
  } finally {Renderer.prototype.setAnimationLoop=oldLoop;performance.now=oldNow;}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
