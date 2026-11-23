"""Execute eave extraction, landing, GPU lifecycle and the real household viewer."""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node
from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const E=await import(file('static/twin/sky/eave_streams.js'));
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {roofMesh}=await import(file('static/twin/twin_roof.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const plan=structuredClone(input.plan),kit={materials:{}},twin=buildTwin(plan,kit,'high');await twin.ready;
const camera=new THREE.PerspectiveCamera(38,1,.1,1000);camera.position.set(0,5,10);const target=new THREE.Vector3();camera.lookAt(target);camera.updateMatrixWorld();
await test('real owner roof envelopes yield exposed horizontal downhill eaves, stable spacing, and valid landing heights',()=>{
 const begin=performance.now(),{eaves,instances}=E.eaveInstances(plan,twin.roofSurfaces,kit),buildMs=performance.now()-begin;
 assert.ok(eaves.length>10&&instances.length>900,'real household roofs need a dense heavy-rain reservoir');
 const actualKinds=new Set(plan.buildings.flatMap(b=>b.roof.sections.filter(s=>s.kind!=='flat').map(s=>s.kind)));
 for(const kind of actualKinds)assert.ok(eaves.some(e=>e.kind===kind),kind);
 const seen=new Set();
 for(const e of eaves){assert.ok(Math.abs(e.a[1]-e.b[1])<1e-4);assert.ok(Math.hypot(e.b[0]-e.a[0],e.b[2]-e.a[2])>.01);
  const key=[e.a,e.b].flat().map(v=>v.toFixed(4)).join(',');assert.ok(!seen.has(key));seen.add(key);
  const points=instances.filter(i=>i.eave===e).sort((a,b)=>a.top[0]-b.top[0]||a.top[2]-b.top[2]);
  for(let n=1;n<points.length;n++){const d=Math.hypot(points[n].top[0]-points[n-1].top[0],points[n].top[2]-points[n-1].top[2]);
   if(e.pan)assert.ok(d>=.05&&d<=.15,`pan spacing ${d}`);
   else if(e.pitch)assert.ok(Math.abs(d-e.pitch)<1e-4,`trough pitch ${d}`);
   else assert.ok(d>=.0649&&d<=.1151,`heavy fallback spacing ${d}`);}
 }
 assert.ok(instances.every(i=>Number.isFinite(i.bottom)&&i.top[1]-i.bottom>.079));
 console.log('OWNER_COST',JSON.stringify({eaves:eaves.length,kinds:[...new Set(eaves.map(e=>e.kind))],instances:instances.length,
  landingKinds:[...new Set(instances.map(i=>i.landing))],draws:2,programs:1,buildMs}));
 assert.ok(eaves.some(e=>e.kind==='attachment'),'owner awnings must not disappear outside the envelope');
});
function fixture(sections,extra={}){return {buildings:[{id:'b',position:[0,0],levels:[],rooms:[],roof:{sections},...extra}]};}
const section=(kind='gable',extra={})=>({kind,rect:[0,0,20,12],plate:10,pitch:6,ridge:'x',overhang:1,...extra});
await test('gable rakes and ridge, hip ridges/valleys, shed high edge, flat roofs and partial abutments emit nothing',()=>{
 for(const [kind,n] of [['gable',2],['hip',4],['shed',1],['flat',0]]){
  const p=fixture([section(kind,{low_side:'y0'})]),e=E.extractEaves(p);
  assert.equal(e.length,n,kind);assert.ok(e.every(e=>Math.abs(e.a[1]-9.5*.3048)<1e-4));
 }
 const p=fixture([section('shed',{low_side:'y0'}),section('shed',{low_side:'y0',rect:[5,-10,15,-1],plate:9.5,overhang:0,pitch:6})]);
 const e=E.extractEaves(p).filter(e=>e.section===0);
 assert.equal(e.length,2,'partial attached wing splits the eave');
 assert.ok(e.every(e=>Math.max(e.a[0],e.b[0])<=5*.3048+1e-4||Math.min(e.a[0],e.b[0])>=15*.3048-1e-4));
 const wall=fixture([section('shed',{low_side:'y0'})],{levels:[{id:'tall',elevation:0,ceiling:20,outline:[[5,-3],[15,-3],[15,-1],[5,-1]]}]});
 assert.equal(E.extractEaves(wall).filter(e=>e.section===0).length,2,'tall abutting wall splits edge');
});
await test('down rays hit lower roofs and decks before terrain, including rotated and raised buildings',()=>{
 const p=fixture([section('shed',{low_side:'y0',plate:20}),section('flat',{rect:[-2,-5,22,-.5],plate:7,overhang:0})]);
 let sample=E.createEaveLandingSampler(p),hit=sample([3,19*.3048,1*.3048]);assert.equal(hit.kind,'roof');assert.ok(Math.abs(hit.height-7*.3048)<1e-6);
 p.buildings[0].roof.sections.pop();p.buildings[0].porches=[{polygon:[[-2,-5],[22,-5],[22,-.5],[-2,-.5]],floor:3}];
 sample=E.createEaveLandingSampler(p);hit=sample([3,19*.3048,1*.3048]);assert.equal(hit.kind,'deck');assert.equal(hit.height,3*.3048);
 p.buildings[0].rotation=90;p.buildings[0].position=[40,30];p.buildings[0].base=4;
 sample=E.createEaveLandingSampler(p);hit=sample([41*.3048,23*.3048,-40*.3048]);assert.equal(hit.kind,'deck');assert.equal(hit.height,7*.3048);
});
await test('standing-seam pans shed several irregular streams; corrugation preserves one point per exposed trough',()=>{
 const p=fixture([section('shed',{low_side:'y0'})]);
 let k={materials:{roof:{asset:'standing_seam'}}},e=E.eaveInstances(p,new Map(),k);assert.ok(e.eaves.every(e=>e.pitch===1.5*.3048));
 assert.ok(e.eaves.every(e=>e.pan));
 const bins=new Map();for(const i of e.instances){const bin=Math.floor(i.top[0]/(1.5*.3048));bins.set(bin,(bins.get(bin)||0)+1);}
 for(let bin=0;bin<13;bin++)assert.ok(bins.get(bin)>=4&&bins.get(bin)<=6,`several streams inside pan ${bin}: ${bins.get(bin)}`);
 const positions=e.instances.map(i=>i.top[0]).sort((a,b)=>a-b),gaps=positions.slice(1).map((p,i)=>p-positions[i]);
 assert.ok(Math.max(...gaps)-Math.min(...gaps)>.015,'pan outlets are irregular');
 p.buildings[0].roof.sections[0].material={id:'corrugated'};k={manifest:{corrugated:{params:{pitch_m:.075}}}};
 assert.ok(E.extractEaves(p,new Map(),k).every(e=>e.pitch===.075));
 const troughs=E.eaveInstances(p,new Map(),k).instances.map(i=>i.top[0]).sort((a,b)=>a-b);
 for(let n=1;n<troughs.length;n++)assert.ok(Math.abs(troughs[n]-troughs[n-1]-.075)<1e-5);
});
await test('two instanced draws share one small sampler-free program; Low submits fewer instances, no instance CPU work',()=>{
 for(const tier of ['high','medium','low']){
  const scene=new THREE.Scene(),e=E.createEaveStreams(scene,{tier});e.setPlan(plan,twin.roofSurfaces,kit);
  const count=e.streams.geometry.instanceCount;assert.equal(e.mist.geometry.instanceCount,count);
  assert.equal(count,Math.floor(e.data.instances.length*(tier==='low'?.35:tier==='medium'?.65:1)));
  assert.equal(e.streams.material.vertexShader,e.mist.material.vertexShader);assert.equal(e.streams.material.fragmentShader,e.mist.material.fragmentShader);
  assert.ok(!e.streams.material.fragmentShader.includes('sampler'));assert.ok(e.streams.frustumCulled);
  let reads=0;const data=e.streams.geometry.attributes.eaveTop,old=data.getX;data.getX=function(){reads++;return old.apply(this,arguments);};
  // Poison the CPU instance list as well: update cannot enumerate it.
  const original=e.data.instances;e.data.instances=new Proxy(original,{get(t,k){if(k==='length'||k===Symbol.iterator)throw Error('per-instance CPU access');return Reflect.get(t,k);}});
  const versions=Object.values(e.streams.geometry.attributes).map(a=>a.version),begin=performance.now();
  const lamps=Array.from({length:4},()=>({at:[0,0,10],rgb:[255,180,120],intensity:1}));
  for(let i=0;i<10000;i++)e.update({flow:1,wet:1},i/60,{camera,target,light:[.3,.4,.5],lamps});
  const ms=(performance.now()-begin)/10000;assert.equal(reads,0);assert.deepEqual(Object.values(e.streams.geometry.attributes).map(a=>a.version),versions);
  assert.ok(ms<.2,`${ms} ms/frame`);
  console.log('TIER_COST',JSON.stringify({tier,streamCapacity:count,mistMax:Math.ceil(count*.5),
    maxTriangles:count*24+Math.ceil(count*.5)*2,streamsAtCamera:e.streams.geometry.instanceCount,mistAtCamera:e.mist.geometry.instanceCount,
    trianglesAtCamera:e.streams.geometry.instanceCount*24+e.mist.geometry.instanceCount*2,draws:2,programs:1,ms}));
  const counts=[];
  for(const flow of [.08,.45,1]){e.update({flow,wet:1},200,{camera});counts.push(e.streams.geometry.instanceCount);}
  assert.ok(counts[0]<counts[1]&&counts[1]<counts[2],'flow controls submitted density, not only transparency');
  e.update({flow:.08,wet:1},201);assert.equal(e.mist.visible,false);assert.equal(e.mist.geometry.instanceCount,0,'no mist in drips');
  e.update({flow:0,wet:0});assert.equal(e.group.visible,false);
  e.update({flow:1,wet:1},0,{level:'floor'});assert.equal(e.group.visible,false);
  e.update({flow:1,wet:1},0,{level:'room'});assert.equal(e.group.visible,false);
  const high=camera.clone();high.position.set(0,100,0);e.update({flow:1,wet:1},0,{camera:high,target});assert.equal(e.group.visible,false);
  e.update({flow:1,wet:1},0,{camera,target});assert.equal(e.group.visible,true);
  const far=camera.clone();far.position.copy(e.streams.geometry.boundingBox.max).addScalar(40);
  e.update({flow:1,wet:1},0,{camera:far});assert.ok(e.streams.geometry.instanceCount<count,'distance removes submitted vertices too');
  far.position.addScalar(100);e.update({flow:1,wet:1},0,{camera:far});assert.equal(e.group.visible,false);assert.equal(e.streams.geometry.instanceCount,0);
  e.dispose();e.dispose();assert.equal(scene.children.length,0);
 }
 const e=E.createEaveStreams(new THREE.Scene());e.setPlan({});e.update({flow:1,wet:1});assert.equal(e.group.visible,false);e.dispose();
});
await test('sustained reservoir decay thins coherent columns quickly; a steady rate change and renewed rain do not keep draining',()=>{
 const e=E.createEaveStreams(new THREE.Scene());e.setPlan(plan,twin.roofSurfaces,kit);
 const values=[];e.update({flow:1,wet:1},0);
 for(let frame=1;frame<=60*160;frame++){
  const seconds=frame/60;e.update({flow:Math.exp(-seconds/600),wet:1},seconds);
  if([1,5,30,60,160].includes(seconds))values.push({seconds,flow:e.uniforms.eaveFlow.value,count:e.streams.geometry.instanceCount,mist:e.mist.visible});
 }
 assert.ok(values[0].flow>.9,'columns may still run in the first second');
 assert.ok(values[1].flow<.85&&values[1].flow>.7);
 assert.ok(values[2].flow<.32&&values[3].flow<.1,'drips within about half a minute, sparse by one minute');
 assert.equal(values[3].mist,false);
 assert.equal(values[4].count,0);assert.equal(e.group.visible,false,'the eave stops drawing while the much slower roof reservoir is still wet');
 e.update({flow:1,wet:1},161);assert.equal(e.uniforms.eaveFlow.value,1,'renewed rain clears the drain latch');
 for(let frame=0;frame<600;frame++)e.update({flow:.45,wet:1},162+frame/60);
 assert.equal(e.uniforms.eaveFlow.value,.45,'one rain-rate step is not a continuing stop');
 console.log('DRAIN_TIMELINE',JSON.stringify(values));e.dispose();
});
await test('actual shader functions vary clear water, desynchronise drops, break thin lower streams and keep spray low and camera-safe',()=>{
 const e=E.createEaveStreams(new THREE.Scene());e.setPlan(plan,twin.roofSurfaces,kit);
 const shape=e.streams.material.vertexShader.split('attribute vec4 eaveTop;')[0]
  .replace(/\bfloat\s+(\w+)\s*\(/g,'function $1(').replace(/(\(|,)\s*float\s+/g,'$1').replace(/\bfloat\s+/g,'let ');
 const fract=x=>x-Math.floor(x),mix=(a,b,t)=>a+(b-a)*t,smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
 const S=new Function('fract','mix','smoothstep','sin','abs','max',shape+'return {eaveWidth,eaveWobble,eavePresence,eaveGlint,eaveOpacity,eaveSpray,eaveSprayHeight,eaveSprayWidth,eaveNearFade};')
  (fract,mix,smoothstep,Math.sin,Math.abs,Math.max);
 const widths=[],alpha=[],wobble=[],phases=[],spray=[];let upper=0,lower=0;
 for(let i=1;i<=300;i++){
  const seed=i/301; widths.push(S.eaveWidth(1,4,seed,1));alpha.push(S.eaveOpacity(0,S.eaveGlint(1,4,seed),1));
  wobble.push(S.eaveWobble(2,i/30,.45));phases.push(S.eavePresence(1,3,5,seed,.45));
  spray.push(S.eaveSpray(.2,.1,i/30,.3,1));
  upper+=S.eavePresence(.1,3,i/30,.01,.45);lower+=S.eavePresence(2.9,3,i/30,.01,.45);
  assert.ok(S.eaveSprayWidth(seed,1)>4*S.eaveSprayHeight(seed,1),'spray hugs the line rather than making round discs');
  assert.equal(S.eaveSpray(.2,.3,i/30,seed,.15),0,'drips never make mist');
  assert.equal(S.eaveSpray(.2,.95,i/30,seed,1),0,'no circular cap above the landing');
 }
 assert.ok(Math.max(...widths)>Math.min(...widths)*4,'independent stream thicknesses');
 assert.ok(alpha.every(v=>v<.1)&&alpha.reduce((a,b)=>a+b,0)/alpha.length<.04,'clear centres, not opaque white wire');
 assert.ok(Math.max(...wobble)-Math.min(...wobble)>.015,'visible slow centimetre-scale wobble');
 assert.ok(phases.some(v=>v===0)&&phases.some(v=>v>.9),'stream gaps do not share a phase');
 assert.ok(lower<upper*.8,'thin columns break up more toward the bottom');
 assert.ok(spray.some(v=>v===0)&&Math.max(...spray)>.02&&Math.max(...spray)<.066,'spray is broken, flickering and translucent');
 assert.ok(S.eaveSpray(.2,.1,4,.3,.45)<S.eaveSpray(.2,.1,4,.3,1),'steady rain has lighter spray');
 assert.equal(S.eaveNearFade(.1,2),0);assert.equal(S.eaveNearFade(2,.08),0);assert.equal(S.eaveNearFade(2,2),1);
 const roofLipDistance=3,landingDistance=.08,oldProjectedWidth=.44*1080/(2*Math.tan(19*Math.PI/180)*landingDistance);
 assert.ok(roofLipDistance>.15&&oldProjectedWidth>1000,'old lip-distance cull admits an oversized near-camera mist quad');
 assert.equal(S.eaveNearFade(landingDistance,landingDistance),0,'actual landing fragments now fade out');
 console.log('SHAPE_PROOF',JSON.stringify({widthMm:[Math.min(...widths)*1000,Math.max(...widths)*1000],faceMeanAlpha:alpha.reduce((a,b)=>a+b,0)/alpha.length,oldProjectedMistPx:oldProjectedWidth}));
 e.dispose();
});
await test('real household viewer wires Rain stopping, cutaway hiding, rebuild and disposal',async()=>{
 let stamp=Date.now(),original=Date.now,v;Date.now=()=>stamp;
 try{
  v=await mountTwin(new Element(),{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});
  assert.equal(v.eaves.data.instances.length,0,'no HA weather allocates no water');v.setTime('day');v.setWeatherPreview('rain-stopping');
  assert.ok(v.eaves.data.instances.length>100);
  const edge=v.eaves.data.eaves[0],mid=edge.a.map((x,i)=>(x+edge.b[i])*.5),n=Math.hypot(...edge.outward);
  v.setCameraState({target:[mid[0],mid[1]-1,mid[2]],position:[mid[0]+edge.outward[0]/n*6,mid[1]-.5,mid[2]+edge.outward[2]/n*6]});v.render();
  assert.equal(v.weather.rate,1);assert.equal(v.eaves.group.visible,true);
  stamp+=25000;v.render();assert.equal(v.weather.rate,0);assert.equal(v.weather.rain_stopped_s,5);assert.ok(v.eaves.uniforms.eaveFlow.value>.9);
  stamp+=65000;v.render();assert.equal(v.weather.wetness,0);assert.equal(v.eaves.group.visible,false);
  const b=v.plan.buildings.find(b=>b.rooms.length),r=b.rooms[0];v.setWeatherPreview('rain-stopping');v.levels.go({building:b.id,floor:r.level},{immediate:true});v.render();assert.equal(v.eaves.group.visible,false);
  const old=v.eaves.streams.geometry;let released=false;old.addEventListener('dispose',()=>released=true);
  const next=structuredClone(v.plan);next.buildings[0].roof.sections[0].plate+=1;
  await v.rebuild(next);v.render();assert.notEqual(v.eaves.streams.geometry,old);assert.ok(released,'rebuilding releases stale landing data');
 }finally{v?.dispose();Date.now=original;}
});
finish();
"""

SOURCE_DRIVER = CLOUD_DRIVER.split("await test('lazy CPU texels")[0] + r"""
const {createEaveStreams}=await import(file('static/twin/sky/eave_streams.js'));
await test('real r187 assembly: one program for streams and mist, no samplers or lit chunks, stable keys through weather and targets',()=>{
 const scene=new THREE.Scene(),r=new Renderer(),e=createEaveStreams(scene),cache=programs(r),lights=makeLights();
 r.toneMapping=THREE.ACESFilmicToneMapping;e.setPlan(input.plan);
 const chunks={...THREE.ShaderChunk};
 for(const target of [null,new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType})]){
  r.setRenderTarget(target);
  const keys=[e.streams,e.mist].map(o=>programSource(r,cache,scene,o,lights).key);assert.equal(keys[0],keys[1]);
  const source=programSource(r,cache,scene,e.streams,lights),budget=uniformBudget(source[2]);
  assert.equal(budget.samplers.length,0);assert.equal(uniformBudget(source[1]).samplers.length,0);assert.ok(budget.vectors<24);
  assert.ok(!source[2].includes('#include'));console.log('EAVE_PROGRAM_BUDGET',JSON.stringify(budget));
  for(const flow of [0,.01,.45,1]){e.update({flow,wet:1},100);assert.equal(programSource(r,cache,scene,e.streams,lights).key,keys[0]);}
  target?.dispose();
 }
 assert.deepEqual(THREE.ShaderChunk,chunks);e.dispose();
});
finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = flatten(assemble(fixture)[0])
    failed = False
    for driver in (DRIVER, SOURCE_DRIVER):
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'plan': plan}, timeout=180)
        print(output)
        failed |= bool(code)
    sys.exit(1 if failed else 0)
