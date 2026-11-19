"""Execute weather mapping, delivery, previews, wind and the real mounted twin in Node."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_tree_once_js import PREFIX as TREE_PREFIX
from test_twin_live_stream_js import DRIVER as STREAM_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const W=await import(file('static/twin/sky/weather.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {grassMaterial}=await import(file('static/twin/yard_grass.js'));
const {installPlantWind,windVector}=await import(file('static/twin/sky/wind.js'));
const {installStageHaze}=await import(file('static/twin/sky/stage_haze.js'));
const now=Date.parse('2026-11-19T14:30:00Z')/1000;
const entity=(state,attributes={})=>({state,attributes});
await test('rain veil and fog share their maximum density, not their sum',()=>{
 for(const precip of ['rain','mix']){
  assert.equal(W.weatherHaze({precip,rate:1}),.25);
  assert.equal(W.weatherHaze({precip,rate:.4,fog:.05}),.1);
  assert.equal(W.weatherHaze({precip,rate:1,fog:.7}),.7);
  assert.equal(W.weatherHaze({precip,rate:1,fog:1}),1);
 }
 for(const precip of ['snow','hail','none'])assert.equal(W.weatherHaze({precip,rate:1,fog:.2}),.2);
 assert.equal(W.weatherHaze({rate:NaN,fog:Infinity}),0);
});
await test('every HA condition and missing/invalid quantities gives a finite defined state',()=>{
 const kinds={rainy:['rain',.45],pouring:['rain',1],'lightning-rainy':['rain',.8],snowy:['snow',.5],'snowy-rainy':['mix',.5],hail:['hail',.7]};
 for(const condition of ['sunny','clear-night','partlycloudy','cloudy','exceptional','fog','lightning','windy','windy-variant',...Object.keys(kinds),'unknown','unavailable','other']){
  const s=W.weatherState(entity(condition),{}, {},now);
  assert.equal(s.precip,kinds[condition]?.[0]||'none');assert.equal(s.rate,kinds[condition]?.[1]||0);
  for(const key of ['rate','fog','windMps','windToDeg','wetness','snow_cm','puddles'])assert.ok(Number.isFinite(s[key]),key);
  assert.equal(s.fog,condition==='fog'?1:0);assert.equal(s.windMps,0);
 }
 for(const e of [null,entity('unavailable'),{...entity('pouring'),stale:true}]){
  const s=W.weatherState(e,{wetness:1,snow_cm:8,puddles:1},{rain:{value:1}},now);
  assert.equal(s.precip,'none');assert.equal(s.wetness,0);assert.equal(s.snow_cm,0);assert.equal(s.windMps,0);
 }
 const old={...entity('rainy'),last_updated:'2000-01-01'};assert.equal(W.weatherState(old).rate,.45,'timestamps are not freshness');
});
await test('current hourly forecast, sensor overrides, units, real zeroes and stale transport',()=>{
 const e=entity('rainy',{forecast:[{datetime:'2026-11-19T13:00:00Z',precipitation:8},{datetime:'2026-11-19T14:00:00Z',precipitation:2}],wind_speed:36,wind_speed_unit:'km/h',wind_bearing:90,visibility:3,temperature:32,temperature_unit:'°F'});
 const s=W.weatherState(e,{snow_cm:8,wetness:.8,puddles:.5}, {},now);
 assert.equal(s.rate,.25);assert.equal(s.windMps,10);assert.equal(s.windToDeg,270);assert.equal(s.fog,.5);assert.equal(s.temperatureC,0);assert.equal(s.snow_cm,8);
 for(const [unit,value] of [['mph',22.3693629205],['m/s',10],['kn',10/.5144]])assert.ok(Math.abs(W.weatherState(entity('sunny',{wind_speed:value,wind_speed_unit:unit})).windMps-10)<1e-8);
 const sensors={rain:{state:'off'},wind_speed:{state:'0',unit:'m/s'},wind_direction:{value:0},temperature:{state:'50',unit:'°F'}};
 const zero=W.weatherState(e,{},sensors,now);assert.equal(zero.rate,0);assert.equal(zero.precip,'none');assert.equal(zero.windMps,0);assert.equal(zero.windToDeg,180);assert.equal(zero.temperatureC,10);
 assert.equal(W.weatherState(entity('sunny'),{}, {rain:{state:'on'}},now).rate,.5);
 assert.equal(W.weatherState(e,{}, {rain:{state:'4',unit:'mm/h'}},now).rate,.5);
 assert.equal(W.weatherState(e,{}, {rain:{state:'unavailable'}},now).rate,.25);
 assert.equal(W.weatherState(entity('rainy',{forecast:[{datetime:'2026-11-19T14:00:00Z',precipitation:0}]}),{}, {},now).rate,.1);
 assert.equal(W.weatherState(entity('fog',{visibility:10})).fog,1);
 const ground={updated:now,wetness:1,snow_cm:8,puddles:1,source:{entity:'weather.home',values:{condition:'snowy',rate:.5,wind_speed:5,wind_bearing:45,temperature:-2},sensors:{}}};
 assert.equal(W.weatherState(W.sourceEntity(ground),ground,{},now).windMps,5);
 ground.source.stale=true;assert.equal(W.weatherState(W.sourceEntity(ground),ground,{},now).snow_cm,0);
});
await test('failed delivery marks the source stale and in-flight changes get a trailing refresh',async()=>{
 let release,calls=0,fail=false;const updates=[],timers=new Map();let seq=0;
 const poll=W.mountWeatherState({api:async()=>{calls++;if(calls===1)await new Promise(r=>release=r);if(fail)throw Error('offline');return {ok:true,json:async()=>({source:{entity:'weather.home',values:{condition:'pouring'}}})};},onChange:x=>updates.push(x),setTimer:(fn)=>{timers.set(++seq,fn);return seq;},clearTimer:id=>timers.delete(id)});
 const pending=poll.refresh();poll.changed('weather.home');release();await pending;
 await new Promise(r=>setImmediate(r));assert.equal(calls,2);
 fail=true;await poll.refresh();assert.equal(updates.at(-1).source.stale,true);
 poll.stop();assert.equal(timers.size,0);
});
await test('delivery uses ingress, five-minute poll, relevant existing-stream events and disposal',async()=>{
 const timers=new Map();let seq=0,calls=0,changes=0;
 const payload={updated:now,source:{entity:'weather.home',sensors:{rain:{entity:'binary_sensor.rain'}}}};
 const poll=W.mountWeatherState({api:async(path)=>{assert.equal(path,'api/house/twin/weather-state');calls++;return {ok:true,json:async()=>payload};},onChange:()=>changes++,setTimer:(fn,ms)=>{assert.equal(ms,300000);timers.set(++seq,fn);return seq;},clearTimer:id=>timers.delete(id)});
 await poll.refresh();assert.equal(calls,1);assert.equal(changes,1);
 poll.changed('light.kitchen');await Promise.resolve();assert.equal(calls,1);
 await poll.changed('weather.home');assert.equal(calls,2);
 await poll.changed('binary_sensor.rain');assert.equal(calls,3);
 await [...timers.values()][0]();assert.equal(calls,4);
 poll.stop();assert.equal(timers.size,0);await poll.refresh();assert.equal(calls,4);
});
await test('preview deadline is 120 seconds and independent of live polls',()=>{
 const timers=new Map();let seq=0,changed=0,clock=1000;
 const p=W.createWeatherPreview(()=>changed++,{now:()=>clock,setTimer:(fn,ms)=>{assert.equal(ms,120000);timers.set(++seq,fn);return seq;},clearTimer:id=>timers.delete(id)});
 for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){
  p.set(name);const s=p.get();assert.ok(s);assert.equal(timers.size,1);
  if(['rain','pouring','thunderstorm'].includes(name)){
   assert.equal(s.wetness,0);assert.equal(s.puddles,0);
   const start=clock;
   for(const seconds of [9,27,45,63,81,90,119]){
    clock=start+seconds*1000;const ramp=p.get();
    assert.equal(ramp.wetness,Math.min(1,seconds/90));assert.equal(ramp.puddles,ramp.wetness);
    assert.equal(ramp.rate,s.rate);assert.equal(p.deadline,start+120000);
   }
  }
  if(name==='snow')assert.equal(s.snow_cm,8);
  if(name==='rain')assert.equal(s.clouds.type,'nimbostratus');
  if(name==='thunderstorm')assert.ok(s.clouds.lightning);
 }
 [...timers.values()][0]();assert.equal(p.get(),null);assert.equal(changed,7);
 p.set('rain');p.set(null);assert.equal(p.get(),null);assert.equal(timers.size,0);p.stop();
});
await test('grass and plant uniforms change without keys, shaders or samplers changing; low tier stays still',()=>{
 const scene=new THREE.Scene(),grass=grassMaterial(new THREE.MeshStandardMaterial()),leaves=new THREE.MeshStandardMaterial({name:'leaves'}),branches=new THREE.MeshStandardMaterial({name:'branches'});
 const geo=new THREE.BoxGeometry(1,10,1);scene.add(new THREE.Mesh(geo,grass));
 const tree=new THREE.Group();tree.userData.placedPlant=true;leaves.userData.plantWind='leaves';branches.userData.plantWind='branches';tree.add(new THREE.Mesh(geo,leaves),new THREE.Mesh(geo,branches));scene.add(tree);
 const wind=installPlantWind(scene,{tier:'high'});wind.prepare();
 const compile=m=>{const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(s,{});return s;};
 const keys=[grass,leaves,branches].map(m=>m.customProgramCacheKey()),shaders=[grass,leaves,branches].map(compile);
 for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){
  const s=W.previewWeather(name),v=windVector(s,180);wind.update(10,s,180);grass.userData.grassUniforms.grassWind.value.set(...v);
  assert.deepEqual([grass,leaves,branches].map(m=>m.customProgramCacheKey()),keys);
  [grass,leaves,branches].forEach((m,i)=>assert.equal(compile(m).vertexShader,shaders[i].vertexShader));
 }
 assert.ok(shaders[1].vertexShader.includes('plantWind'));assert.ok(!shaders[1].fragmentShader.includes('plantWind'));
 assert.ok(!THREE.ShaderChunk.lights_pars_begin.includes('plantWind'));
 assert.ok(!shaders[1].vertexShader.includes('sampler'));assert.ok(shaders[2].vertexShader.includes('plantBranch'));
 const lowScene=new THREE.Scene(),low=new THREE.MeshStandardMaterial({name:'leaves'}),root=new THREE.Group();root.userData.placedPlant=true;low.userData.plantWind='leaves';root.add(new THREE.Mesh(geo,low));lowScene.add(root);
 const before=low.customProgramCacheKey();const still=installPlantWind(lowScene,{tier:'low'});still.prepare();assert.equal(low.customProgramCacheKey(),before);
 const east=windVector(W.weatherState(entity('sunny',{wind_speed:10,wind_speed_unit:'m/s',wind_bearing:270})),180);assert.ok(east[0]>0&&Math.abs(east[1])<1e-8);
 wind.dispose();still.dispose();geo.dispose();grass.dispose();leaves.dispose();branches.dispose();low.dispose();
});
await test('fog scales existing radius to 15 percent with no additional lit uniforms',()=>{
 const scene=new THREE.Scene(),m=new THREE.MeshStandardMaterial(),geo=new THREE.BoxGeometry();scene.add(new THREE.Mesh(geo,m));
 const haze=installStageHaze(scene,{horizon:()=>new THREE.Color(.3,.4,.5)});haze.set({radius:100});haze.prepare();
 const s={uniforms:{},vertexShader:'',fragmentShader:''};m.onBeforeCompile(s,{});const key=m.customProgramCacheKey(),names=Object.keys(s.uniforms);
 haze.set({fog:1});assert.ok(Math.abs(s.uniforms.stageRadius.value-15)<1e-10);assert.equal(m.customProgramCacheKey(),key);assert.deepEqual(Object.keys(s.uniforms),names);
 haze.set({radius:200});assert.ok(Math.abs(s.uniforms.stageRadius.value-30)<1e-10);haze.set({fog:0});assert.equal(s.uniforms.stageRadius.value,200);haze.dispose();geo.dispose();m.dispose();
});
await test('real household mount: weather previews, Now, live editor opt-in and neutral restoration',async()=>{
 const mount=async(editor=false)=>{const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});};
 let v,e;try{
  v=await mount();e=await mount(true);const states={'weather.home':entity('pouring',{wind_speed:12,wind_speed_unit:'m/s'})};
  for(const view of [v,e])view.live={peek:()=>states,stale:()=>false,draw(){},stop(){},closeRoom(){}};
  v.setTime('day');e.setTime('day');assert.equal(v.weather.precip,'rain');assert.equal(e.weather.precip,'none');
  for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){v.setWeatherPreview(name);assert.equal(v.weather.preview,name);assert.equal(v.clouds.uniforms.cloudCoverage.value,v.weather.clouds.coverage);}
  v.setTime('now');assert.equal(v.weather.preview,null);assert.equal(v.weather.rate,1);
  v.setWeatherPreview('snow');const saved=v.saveView();v.setTime('now');v.restoreView(saved);assert.equal(v.state.weatherPreview,null,'restoring a camera cannot revive a preview cancelled by Now');
  const {mountLighting}=await import(file('static/twin/editor/lighting.js'));
  const host=new Element();for(const choice of ['day','night','now','unlit','live']){const b=new Element('button');b.dataset.editorLighting=choice;host.append(b);}
  const storage={getItem:()=>null,setItem(){}};const lighting=mountLighting(e,host,{storage});
  await click(host.querySelector('[data-editor-lighting="live"]'));assert.equal(e.weather.precip,'rain');assert.equal(e.state.time,'now');assert.equal(e.state.liveWeather,true);
  lighting.select('day');assert.equal(e.weather.wetness,0);assert.equal(e.weather.windMps,0);
  e.setWeatherPreview('snow');assert.equal(e.weather.snow_cm,8);e.setTime('now');assert.equal(e.weather.snow_cm,0);
 }finally{v?.dispose();e?.dispose();}
});
finish();
"""

TREE_DRIVER = TREE_PREFIX + r"""
const THREE=await import('three');
const {presetTree,buildYard}=await import(file('static/twin/twin_yard.js'));
const {installPlantWind}=await import(file('static/twin/sky/wind.js'));
const {previewWeather}=await import(file('static/twin/sky/weather.js'));
await test('real EZ-Tree oak and shrub keep trunk vertices fixed and sway only marked materials and viewing clones',async()=>{
 for(const preset of ['Oak Small','Bush 1']){
  const t=presetTree(preset,7),g=t.branchesMesh.geometry,mask=g.attributes.plantBranch;
  assert.equal(mask.count,g.attributes.position.count);
  const rootCount=(t.options.branch.sections[0]+1)*(t.options.branch.segments[0]+1);
  assert.ok(Array.from(mask.array.slice(0,rootCount)).every(v=>v===0),'every trunk vertex stays fixed');
  assert.ok(Array.from(mask.array.slice(rootCount)).some(v=>v>0));
  t.traverse(o=>{o.geometry?.dispose();o.material?.dispose();});
 }
 const plan={buildings:[],site:{planting:[{id:'tree',preset:'Oak Small',seed:7,height:15,at:[0,0]},{id:'shrub',preset:'Bush 1',height:3,at:[10,0]}]}};
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true});
 const scene=new THREE.Scene();scene.add(group);const wind=installPlantWind(scene,{tier:'high'});wind.prepare();
 const mats=new Set();scene.traverse(o=>{for(const m of [].concat(o.material||[]))if(m.userData.plantWind)mats.add(m);});
 assert.ok([...mats].some(m=>m.userData.plantWind==='leaves'));assert.ok([...mats].some(m=>m.userData.plantWind==='branches'));
 const compile=m=>{const s={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(s,{});return s;};
 for(const material of mats){
  const key=material.customProgramCacheKey(),s=compile(material),clone=material.clone();scene.add(new THREE.Mesh(new THREE.BoxGeometry(),clone));wind.prepare();
  assert.equal(clone.customProgramCacheKey(),key);assert.equal(compile(clone).uniforms.plantWind,wind.uniforms.plantWind);
  assert.equal((s.vertexShader.match(/uniform vec3 plantWind;/g)||[]).length,1);
  for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){wind.update(10,previewWeather(name),90);assert.equal(material.customProgramCacheKey(),key);assert.equal(compile(material).vertexShader,s.vertexShader);}
 }
 wind.dispose();group.userData.releasePlants?.();
});
finish();
"""

STREAM_EXTRA = r"""
check('weather pushes refresh the weather read through the existing single stream',async()=>{
 const t=await mount();const changes=[];t.view.weatherChanged=id=>changes.push(id);
 try{
  const es=sources[0];es.emit({entity_id:'weather.home',state:{state:'rainy',attributes:{}}});
  await wait(30);assert.equal(sources.length,1);assert.ok(changes.includes('weather.home'));
  assert.equal(t.live.peek()['weather.home'].state,'rainy');
  es.emit({entity_id:'binary_sensor.rain',state:{state:'off',attributes:{}}});await wait(30);
  assert.ok(changes.includes('binary_sensor.rain'),'configured sensors can wake the weather read even before card filtering');
 }finally{t.cleanup();}
});
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = flatten(assemble(fixture)[0])
    failed = False
    for driver, payload in [(DRIVER, {'root': ROOT.as_posix(), 'plan': plan}),
                            (TREE_DRIVER, {'root': ROOT.as_posix()}),
                            (STREAM_DRIVER.replace('let passed = 0;', STREAM_EXTRA + '\nlet passed = 0;'), {'root': ROOT.as_posix()})]:
        code, output = run_node(driver, payload, timeout=180)
        print(output)
        failed |= bool(code)
    sys.exit(1 if failed else 0)
