"""Shared cloud model: real r187 textures and a CPU density reference, offline."""
from pathlib import Path
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
noise.dispose();finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(out)
    sys.exit(code if code is not None else 1)
