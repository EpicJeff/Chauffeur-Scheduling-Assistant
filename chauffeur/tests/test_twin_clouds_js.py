"""Shared cloud model: real r187 textures and a CPU density reference, offline."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const THREE = await import('three');
const {cloudState, windSpeedMps, cloudDrift, createCloudNoise, sampleCloudDensity, CLOUD_GLSL, CLOUD_TYPES} =
  await import(file('static/twin/sky/clouds.js'));
const {perlin3, worley3, sampleVolume} = await import(file('static/twin/sky/cloud_noise.js'));
const {conditions} = await import(file('static/twin/sky/overcast.js'));
await test('every HA condition has the specified coverage, type and lightning eligibility',()=>{
  const types={sunny:'cumulus','clear-night':'none',partlycloudy:'cumulus',cloudy:'stratocumulus',
    fog:'nimbostratus',rainy:'nimbostratus',pouring:'nimbostratus',snowy:'nimbostratus',
    'snowy-rainy':'nimbostratus',hail:'nimbostratus',exceptional:'nimbostratus',
    lightning:'cumulonimbus','lightning-rainy':'cumulonimbus',windy:'cumulus','windy-variant':'cumulus'};
  assert.deepEqual(Object.keys(types).sort(),Object.keys(conditions).sort());
  for(const [condition,type] of Object.entries(types)) {
    const weather={state:condition}, before=JSON.stringify(weather), state=cloudState(weather,{now:123});
    assert.equal(state.coverage,conditions[condition],condition);assert.equal(state.type,type,condition);
    assert.equal(state.lightning,condition==='lightning'||condition==='lightning-rainy');
    assert.equal(JSON.stringify(weather),before);assert.deepEqual(cloudState(weather,{now:123}),state);
  }
});
await test('coverage overrides the shared table; missing and explicitly stale weather stay clear',()=>{
  for(const [cloud_coverage,expected] of [[0,0],[25,.25],[100,1],[-20,0],[120,1]])
    assert.equal(cloudState({state:'rainy',attributes:{cloud_coverage}}).coverage,expected);
  for(const cloud_coverage of [null,'',NaN,Infinity,'bad'])
    assert.equal(cloudState({state:'cloudy',attributes:{cloud_coverage}}).coverage,.85);
  for(const weather of [null,{}, {state:'unknown'}, {state:'unavailable'}, {state:''},
    {state:'lightning',stale:true,attributes:{cloud_coverage:100}}]) {
    const state=cloudState(weather);assert.equal(state.coverage,0);assert.equal(state.type,'none');assert.equal(state.lightning,false);
  }
  // last_changed is not freshness: live.stale() owns this, even for an unchanged HA state.
  assert.equal(cloudState({state:'cloudy',last_changed:'2000-01-01'},{now:Date.now()}).coverage,.85);
  assert.equal(cloudState({state:'custom',attributes:{cloud_coverage:75}}).coverage,.75);
  assert.equal(cloudState({state:'custom'}).coverage,0);
});
await test('wind units, FROM bearing, calm and missing data obey the exact drift rule',()=>{
  for(const [value,unit,expected] of [[36,'km/h',10],[10,'kn',5.144],[10,'mph',4.4704],[4,'m/s',4],[0,'m/s',0]])
    assert.ok(Math.abs(windSpeedMps(value,unit)-expected)<1e-10);
  for(const [value,unit] of [[null,'m/s'],['','m/s'],[NaN,'m/s'],[Infinity,'mph'],[-1,'kn'],[10,'bad']])
    assert.equal(windSpeedMps(value,unit),null);
  const east=cloudState({state:'cloudy',attributes:{wind_speed:36,wind_speed_unit:'km/h',wind_bearing:270}});
  assert.equal(east.windMps,10);assert.equal(east.windToDeg,90);
  const drift=cloudDrift(east,10);assert.ok(Math.abs(drift.eastM-1200)<1e-9);assert.ok(Math.abs(drift.northM)<1e-9);
  const fallback=cloudState({state:'cloudy'});assert.equal(fallback.windMps,3);assert.equal(fallback.windToDeg,90);
  assert.equal(cloudDrift(fallback,1).speedMps,36);
  const calm=cloudState({state:'sunny',attributes:{wind_speed:0,wind_speed_unit:'m/s',wind_bearing:0}});
  assert.equal(calm.windMps,0);assert.equal(cloudDrift(calm,1).speedMps,12);
  assert.equal(cloudState({state:'windy',attributes:{wind_bearing:-90}}).windToDeg,90);
});
await test('continuous Perlin and Worley tile on every axis, including negative coordinates',()=>{
  for(const noise of [perlin3,worley3]) for(const period of [4,8,16]) for(const p of [[0,1.2,2.3],[-.001,.27,2.9],[.31,.67,.92]]) {
    const value=noise(...p,period);
    assert.ok(Number.isFinite(value));
    for(let axis=0;axis<3;axis++) { const q=[...p];q[axis]+=period;assert.ok(Math.abs(value-noise(...q,period))<1e-6); }
    assert.equal(value,noise(...p,period));
  }
});
const started=performance.now(), noise=createCloudNoise();
console.log('Default cloud noise generation: '+Math.round(performance.now()-started)+' ms, '+(noise.base.image.data.byteLength+noise.detail.image.data.byteLength)+' bytes');
await test('default textures are deterministic periodic 128^3 and 32^3, filtered and disposable',()=>{
  const again=createCloudNoise({size:16,detail:8}), repeat=createCloudNoise({size:16,detail:8});
  for(const [texture,size] of [[noise.base,128],[noise.detail,32]]) {
    assert.ok(texture.isData3DTexture);assert.equal(texture.image.width,size);assert.equal(texture.image.height,size);assert.equal(texture.image.depth,size);
    assert.equal(texture.image.data.length,size**3*4);assert.equal(texture.format,THREE.RGBAFormat);
    assert.equal(texture.wrapS,THREE.RepeatWrapping);assert.equal(texture.wrapT,THREE.RepeatWrapping);assert.equal(texture.wrapR,THREE.RepeatWrapping);
    assert.equal(texture.minFilter,THREE.LinearFilter);assert.equal(texture.magFilter,THREE.LinearFilter);assert.equal(texture.generateMipmaps,false);
    const volume=texture.image;
    for(const p of [[0,.23,.71],[.13,0,.29],[.19,.47,0]]) for(let axis=0;axis<3;axis++) {
      const q=[...p];q[axis]+=1;
      sampleVolume(volume,p).forEach((v,i)=>assert.ok(Math.abs(v-sampleVolume(volume,q)[i])<1e-6));
    }
    assert.ok(new Set(volume.data).size>100,'noise has a useful range');
  }
  assert.deepEqual(again.base.image.data,repeat.base.image.data);assert.deepEqual(again.detail.image.data,repeat.detail.image.data);
  let disposals=0;again.base.addEventListener('dispose',()=>disposals++);again.detail.addEventListener('dispose',()=>disposals++);
  again.dispose();again.dispose();assert.equal(disposals,2);repeat.dispose();
  assert.throws(()=>createCloudNoise({size:0}));
});
await test('CPU port of shared density is empty outside the shell and with no coverage; full cover has volume',()=>{
  for(const type of ['cumulus','stratocumulus','stratus','nimbostratus','cumulonimbus']) {
    const low=['stratus','nimbostratus'].includes(type), bottom=low?500:1500, top=low?1500:4000;
    for(const y of [0,bottom-1,top+1,10000]) assert.equal(sampleCloudDensity([0,y,0],{...noise,type,coverage:1}),0);
    let sum=0;
    for(let x=-6000;x<=6000;x+=1000) for(const h of [.2,.5,.8]) {
      const p=[x,bottom+(top-bottom)*h,1300];
      assert.equal(sampleCloudDensity(p,{...noise,type,coverage:0}),0);
      const d=sampleCloudDensity(p,{...noise,type,coverage:1});assert.ok(Number.isFinite(d)&&d>=0&&d<=1);sum+=d;
    }
    assert.ok(sum>1,`${type} has a solid body`);
  }
  assert.equal(sampleCloudDensity([0,2200,0],{...noise,type:'none',coverage:1}),0);
  // At the geometric horizon, the ray reaches the layer through Earth curvature.
  assert.ok(sampleCloudDensity([160000,0,0],{...noise,type:'cumulus',coverage:1})>0);
});
await test('partly cloudy has billows and gaps; coverage grows monotonically into an unbroken low sheet',()=>{
  let partly=0,full=0;
  for(let x=0;x<12000;x+=750) for(let z=0;z<12000;z+=750) {
    let a=0,b=0;
    for(const h of [.2,.35,.5,.65,.8]) {
      const p=[x,1500+2500*h,z];
      const d=sampleCloudDensity(p,{...noise,type:'cumulus',coverage:.4});
      const e=sampleCloudDensity(p,{...noise,type:'cumulus',coverage:1});
      assert.ok(e>=d);a=Math.max(a,d);b=Math.max(b,e);
    }
    if(a>.01)partly++;if(b>.01)full++;
    assert.ok(sampleCloudDensity([x,900,z],{...noise,type:'nimbostratus',coverage:1})>.1,'overcast sheet has no holes');
  }
  console.log('Cloud columns with density > .01: partly '+partly+'/256, full '+full+'/256');
  assert.ok(partly>10 && partly<230,'partly cloudy has both substantial billows and gaps');assert.ok(full>partly);
});
await test('one shared shader supplies density, lighting and premultiplied march without state defines',()=>{
  for(const name of ['cloudDensity','cloudLight','marchClouds']) assert.ok(CLOUD_GLSL.includes(name+'('));
  assert.ok(CLOUD_GLSL.includes('sampler3D'));assert.ok(!CLOUD_GLSL.includes('#define'));
  for(const type of ['none','cumulus','stratocumulus','stratus','nimbostratus','cumulonimbus']) assert.ok(Number.isFinite(CLOUD_TYPES[type]));
});
await test('lightning intervals, durations and double-flash probability use ruling 8',async()=>{
  const {createLightning}=await import(file('static/twin/sky/clouds.js'));
  for(const value of [0,.299,.3,.999999,1]) {
    const lightning=createLightning({random:()=>value});
    const options={enabled:true,locate:()=>[0,2500,0]};
    assert.equal(lightning.frame(0,options).strength,0);
    const interval=4+14*value,duration=.08+.08*value;
    assert.equal(lightning.frame(interval-.001,options).strength,0);
    lightning.frame(interval,options);
    assert.ok(Math.abs(lightning.frame(interval+duration/4,options).strength-Math.SQRT1_2)<1e-9);
    assert.ok(lightning.frame(interval+duration/2,options).strength>.99);
    assert.ok(Math.abs(lightning.frame(interval+duration*3/4,options).strength-Math.SQRT1_2)<1e-9);
    assert.equal(lightning.frame(interval+duration+.001,options).strength,0);
    const second=interval+duration+.06+.06*value;
    assert.equal(lightning.frame(second+duration/2,options).strength>.99,value<.3,'30% double threshold');
    assert.equal(lightning.frame(interval+2*duration+.13,options).strength,0);
    assert.equal(lightning.frame(interval*2-.001,options).strength,0);
    lightning.frame(interval*2,options);
    assert.ok(lightning.frame(interval*2+duration/2,options).strength>.99);
  }
});
await test('strike positions come from the nearest dense cumulonimbus column and remain inside real density',async()=>{
  const {findLightningCell}=await import(file('static/twin/sky/clouds.js'));
  const options={...noise,coverage:1,type:'cumulonimbus',offset:[640,0,-120]};
  for(const centre of [[0,0],[12000,-8000]]) {
    const point=findLightningCell(p=>sampleCloudDensity(p,options),centre,()=>.73);
    assert.ok(point);assert.ok(sampleCloudDensity(point,options)>.2);
    assert.ok(Math.hypot(point[0]-centre[0],point[2]-centre[1])<=6000);
  }
  const calls=[],density=p=>{calls.push(p);return p[0]>=1000&&Math.abs(p[2])<1?1:0;};
  const p=findLightningCell(density,[0,0],()=>.5);assert.equal(p[0],1000);assert.equal(p[2],0);
  assert.equal(findLightningCell(()=>0,[0,0]),null,'never flash in empty sky');
});
await test('only thunder conditions flash; matchMedia cancels and restarts the clock while clouds remain',async()=>{
  const {createCloudPass}=await import(file('static/twin/sky/cloud_pass.js'));
  registerHooks({load(url,ctx,next){
    if(url.endsWith('three.module.js?lightning-keys'))return {format:'module',shortCircuit:true,
      source:readFileSync(new URL(url),'utf8')+'\nexport {WebGLPrograms};'};
    return next(url,ctx);
  }});
  const {WebGLPrograms}=await import(file('static/vendor/three-r187/three.module.js')+'?lightning-keys');
  const renderer=new Renderer(),scene=new THREE.Scene();
  renderer.state={buffers:{depth:{getReversed:()=>false}}};
  const programs=WebGLPrograms(renderer,{get:t=>t},{has:()=>false},{precision:'highp',getMaxPrecision:()=> 'highp'},
    {},{numPlanes:0,numIntersection:0});
  const lights=Object.fromEntries(['sun','directional','point','spot','spotLightMap','rectArea','hemi',
    'sunShadowMap','directionalShadowMap','pointShadowMap','spotShadowMap'].map(k=>[k,[]]));
  lights.hemi=[{}];lights.numSpotLightShadowsWithMaps=0;lights.numLightProbes=0;
  const actualKey=object=>programs.getProgramCacheKey(programs.getParameters(object.material,lights,[],scene,object,[]));
  const oldMedia=window.matchMedia,motion={matches:false},queries=[];
  window.matchMedia=query=>{queries.push(query);return motion;};
  try {
    const c=createCloudPass(renderer,{tier:'high',noise,random:()=>.5});
    try {
      const u=c.uniforms.cloudLightning,version=c.material.version,key=c.material.customProgramCacheKey(),defines={...c.material.defines};
      const march=new THREE.Mesh(new THREE.PlaneGeometry(),c.material),lit=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshPhysicalMaterial());
      const actualKeys=[actualKey(march),actualKey(lit)];
      for(const condition of Object.keys(conditions)) {
        c.flash(0,{enabled:false});
        c.update(cloudState({state:condition,attributes:{cloud_coverage:100}}));
        c.flash(0);c.flash(11);const peak=c.flash(11.06);
        assert.equal(peak>.99,['lightning','lightning-rainy'].includes(condition),condition);
        if(peak)assert.ok(sampleCloudDensity(u.value.toArray().slice(0,3),{...noise,coverage:1,type:'cumulonimbus'})>.2);
        assert.equal(c.uniforms.cloudLightning,u);assert.equal(c.material.version,version);
        assert.equal(c.material.customProgramCacheKey(),key);assert.deepEqual(c.material.defines,defines);
        assert.deepEqual([actualKey(march),actualKey(lit)],actualKeys,'real r187 program keys stay fixed through peak and fade');
      }
      c.update(cloudState({state:'lightning'}));c.flash(20,{enabled:false});c.flash(20);c.flash(31);
      assert.ok(c.flash(31.06)>.99);motion.matches=true;
      assert.equal(c.flash(31.061),0);assert.equal(u.value.w,0);assert.equal(c.active,true);
      c.flash(100);motion.matches=false;c.flash(100);assert.equal(c.flash(110.999),0);
      c.flash(111);assert.ok(c.flash(111.06)>.99);
      c.flash(112,{enabled:false});c.update({coverage:0});c.flash(200);assert.equal(c.flash(220),0);
      c.dispose();assert.equal(c.flash(230),0);
      march.geometry.dispose();lit.geometry.dispose();lit.material.dispose();
    } finally {c.dispose();}
    assert.deepEqual(queries,['(prefers-reduced-motion: reduce)']);
  } finally {window.matchMedia=oldMedia;}
});
await test('point-light math is finite at the source and decays; transient flashes never enter or refresh the cube',async()=>{
  const body=CLOUD_GLSL.match(/float cloudLightningWeight\(float distanceM\) \{([\s\S]*?)\n\}/)[1];
  const weight=new Function('distanceM','max',body.replace(/\bfloat\s+/g,'let ')).bind(null);
  assert.equal(weight(0,Math.max),16.6);assert.equal(weight(1500,Math.max),8.6);assert.ok(weight(8000,Math.max)>.6&&weight(8000,Math.max)<1.2);
  for(const d of [0,1,1000,1000000])assert.ok(Number.isFinite(weight(d,Math.max))&&weight(d,Math.max)>0);
  assert.ok(CLOUD_GLSL.includes('light+=vec3(0.7,0.8,1.0)*cloudLightning.w*cloudLightningWeight(length(p-cloudLightning.xyz))'));
  const {createCloudPass}=await import(file('static/twin/sky/cloud_pass.js'));
  const {createSky}=await import(file('static/twin/sky/atmosphere.js'));
  for(const tier of ['low','high']) {
    const r=new Renderer(),c=createCloudPass(r,{tier,noise,random:()=>.5});
    c.update(cloudState({state:'lightning'}));
    const sky=createSky(r,{tier,clouds:c});
    try {
      // Settle the existing state-triggered six-face refresh before a strike.
      for(let i=0;i<6;i++)sky.frame(i*.016);
      let draws=0,cubeUniform=null;const draw=r.render;
      r.render=function(s,eye){if(s.name==='twin-atmosphere'){draws++;cubeUniform=s.children[0].material.uniforms.cloudLightning.value;}return draw.call(this,s,eye);};
      c.flash(0);c.flash(11);assert.ok(c.flash(11.06)>.99);
      sky.frame(.2);assert.equal(draws,0,'flash alone does not invalidate the cube');
      sky.update({sunDir:[0,1,0],force:true});sky.frame(.3);
      assert.equal(cubeUniform.w,0,'even an unrelated time/asset capture during a flash stays unflashed');
    } finally {sky.dispose();c.dispose();}
  }
});
await test('mounted viewer lifts its existing hemisphere only; editor, stale weather, Unlit and reduced motion never flash',async()=>{
  const {mountTwin}=await import(file('static/twin/twin_view.js'));
  const oldNow=performance.now,oldRandom=Math.random,oldMedia=window.matchMedia;
  let now=0;const motion={matches:false};performance.now=()=>now;Math.random=()=>.5;
  window.matchMedia=()=>motion;
  try {
    for(const [tier,editor] of [['low',false],['high',false],['medium',true]]) {
      now=0;motion.matches=false;const host=new Element();if(editor)host.className='editor-shell';
      const v=await mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier,bake:false});
      try {
        v.clouds.uniforms.cloudFade.value=1;
        let weather={state:'lightning'},stale=false;
        v.live={peek:()=>({'weather.local':weather}),stale:()=>stale,stop:()=>{},draw:()=>{}};
        v.render();const hemi=v.scene.children.find(o=>o.isHemisphereLight),baseline=hemi.intensity;
        const objects=[];v.scene.traverse(o=>objects.push([o,o.visible,o.material,o.isLight]));
        now=11000;v.render();now=11060;v.render();
        assert.equal(v.clouds.uniforms.cloudLightning.value.w>.99,!editor);
        assert.ok(Math.abs(hemi.intensity-baseline-(editor?0:1.5))<1e-6);
        for(const [o,visible,material,isLight] of objects){assert.equal(o.visible,visible);assert.equal(o.material,material);assert.equal(o.isLight,isLight);}
        motion.matches=true;v.render();assert.equal(v.clouds.uniforms.cloudLightning.value.w,0);assert.equal(hemi.intensity,baseline);
        assert.equal(v.clouds.uniforms.cloudCoverage.value,editor?0:1);
        motion.matches=false;now=12000;v.render();now=23000;v.render();now=23060;v.render();
        stale=true;v.render();assert.equal(v.clouds.uniforms.cloudLightning.value.w,0);
        stale=false;v.render();now=34060;v.render();now=34120;v.render();
        v.state.unlit=true;v.render();assert.equal(v.clouds.uniforms.cloudLightning.value.w,0);assert.equal(hemi.intensity,0);
      } finally {v.dispose();}
    }
  } finally {performance.now=oldNow;Math.random=oldRandom;window.matchMedia=oldMedia;}
});
await test('GPU-noise viewer finds a strike with lazy exact texels, without whole-volume generation or readback',async()=>{
  const {createCloudPass}=await import(file('static/twin/sky/cloud_pass.js'));
  const gpu={base:new THREE.Data3DTexture(null,128,128,128),detail:new THREE.Data3DTexture(null,32,32,32)};
  const c=createCloudPass(new Renderer(),{tier:'high',noise:gpu,random:()=>.5});
  try {
    c.update(cloudState({state:'lightning'}));c.uniforms.cloudOffset.value.set(1500,0,-500);
    c.flash(0);const start=performance.now();c.flash(11);
    console.log('Cold lightning density search, desktop Node: '+(performance.now()-start).toFixed(3)+' ms');
    assert.ok(c.flash(11.06)>.99);
    const p=c.uniforms.cloudLightning.value.toArray().slice(0,3);
    assert.ok(sampleCloudDensity(p,{...noise,coverage:1,type:'cumulonimbus',offset:[1500,0,-500]})>.2);
    assert.equal(gpu.base.image.data,null);assert.equal(gpu.detail.image.data,null);
  } finally {c.dispose();gpu.base.dispose();gpu.detail.dispose();}
});
noise.dispose();finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan}, timeout=180)
    print(out)
    sys.exit(code if code is not None else 1)
