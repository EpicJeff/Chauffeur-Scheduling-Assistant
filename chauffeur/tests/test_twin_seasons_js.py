"""Season state and generated vegetation, executed in Node without a browser."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_tree_once_js import PREFIX as TREE_PREFIX
from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER
from test_twin_yard_reuse_js import PREFIX as YARD_PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const S=await import(file('static/twin/sky/seasons.js'));
const THREE=await import('three');
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const date=s=>new Date(s+'T12:00:00Z');
await test('latitude phenology: three weeks of green-up and colour, two weeks of drop, mirrored south',()=>{
 assert.deepEqual(S.phenologyDates(40),{spring:95,autumn:285,drop:306,bare:320});
 assert.deepEqual(S.phenologyDates(-35),{spring:88,autumn:293,drop:314,bare:328});
 const at=s=>S.seasonState(date(s),40);
 assert.equal(at('2026-04-05').presence,0);
 assert.equal(at('2026-04-26').presence,1);
 assert.equal(at('2026-10-12').autumn,0);
 assert.equal(at('2026-11-02').autumn,1);
 assert.equal(at('2026-11-02').presence,1);
 assert.equal(at('2026-11-16').presence,0);
 assert.equal(at('2026-01-15').presence,0);
 assert.equal(at('2026-07-15').presence,1);
 assert.equal(S.seasonState(date('2028-03-20'),-90).autumn,1,'21 actual days after February 28 in a leap year');
 assert.equal(S.seasonState(date('2028-04-03'),-90).presence,0,'14 actual days of drop after colour');
 for(const [north,south]of [['2026-03-29','2026-09-29'],['2026-04-19','2026-10-20'],['2026-10-20','2026-04-20'],['2026-11-10','2026-05-11'],['2026-11-24','2026-05-25']]){
  const a=S.seasonState(date(north),35),b=S.seasonState(date(south),-35);
  assert.equal(a.presence,b.presence);assert.equal(a.autumn,b.autumn);
 }
 for(let day=0;day<366;day++)for(const lat of [40,-35,0,90,-90,NaN]){
  const s=S.seasonState(new Date(Date.UTC(2028,0,1+day)),lat);
  for(const key of ['presence','autumn','spring','dormancy'])assert.ok(Number.isFinite(s[key])&&s[key]>=0&&s[key]<=1,key);
 }
});
await test('route lawn, bounded fallback, neutral editor and warm winter preview',()=>{
 const ground={lawn:{dormancy:.65,grass_type:'warm',source:'history'},season:{avg_temp_c:8,history_days:10}};
 const s=S.seasonState(date('2026-07-15'),40,ground);
 assert.equal(s.dormancy,.65);assert.equal(s.grassType,'warm');assert.equal(s.source,'history');assert.equal(s.avgTempC,8);
 assert.equal(S.seasonState(date('2026-01-15'),40).dormancy,.3);
 assert.equal(S.seasonState(date('2026-07-15'),-35).dormancy,.3);
 assert.equal(S.seasonState(date('2026-01-15'),40,{lawn:{grass_type:'warm'}}).dormancy,1);
 const neutral=S.seasonState(date('2026-01-15'),40,ground,{neutral:true});
 assert.equal(neutral.presence,1);assert.equal(neutral.dormancy,0);assert.equal(neutral.autumn,0);
 const winter=S.seasonState(date('2026-07-15'),40,ground,{preview:'winter'});
 assert.equal(winter.presence,0);assert.equal(winter.dormancy,1);
 assert.equal(S.seasonState(date('2026-01-15'),40,ground,{preview:'summer'}).dormancy,0);
 assert.equal(S.seasonState(date('2026-01-15'),40,{lawn:{dormancy:NaN,grass_type:'warm'}}).dormancy,1);
});
await test('previews last exactly 120 seconds, replace their timer, expire and stop',()=>{
 const timers=new Map();let seq=0,changes=0;
 const p=S.createSeasonPreview(()=>changes++,{setTimer:(fn,ms)=>{assert.equal(ms,120000);timers.set(++seq,fn);return seq;},clearTimer:id=>timers.delete(id)});
 for(const name of ['spring','summer','autumn','winter']){p.set(name);assert.equal(p.get(),name);assert.equal(timers.size,1);assert.ok(p.deadline>Date.now());}
 p.set('invalid');assert.equal(p.get(),'winter');
 [...timers.values()][0]();assert.equal(p.get(),null);assert.equal(timers.size,0);assert.equal(changes,5);
 p.set('spring');p.set(null);assert.equal(p.get(),null);p.stop();assert.equal(timers.size,0);
});
await test('retiring a plant geometry frees its shadow pair even while the yard keeps its shared material',()=>{
 const scene=new THREE.Scene(),material=new THREE.MeshStandardMaterial({alphaTest:.5});material.userData.seasonFoliage=true;
 const geometry=new THREE.PlaneGeometry(),mesh=new THREE.Mesh(geometry,material);mesh.castShadow=true;scene.add(mesh);
 const seasons=S.installSeasons(scene);seasons.prepare();let freed=0;
 for(const m of [mesh.customDepthMaterial,mesh.customDistanceMaterial])m.addEventListener('dispose',()=>freed++);
 geometry.dispose();assert.equal(freed,2);material.dispose();assert.equal(freed,2,'no retained listener or double release');seasons.dispose();
});
await test('real household mounted viewer and editor: same route poll, site, Now, camera restore and live opt-in',async()=>{
 const savedFetch=globalThis.fetch,prior=location.search;location.search='?test=1';
 const payload={lawn:{dormancy:.71,grass_type:'warm',source:'history'},season:{avg_temp_c:9,history_days:10},source:{entity:'weather.home',values:{condition:'sunny'}}};
 let reads=0;globalThis.fetch=async url=>{if(String(url).endsWith('api/house/twin/weather-state')){reads++;return {ok:true,json:async()=>payload};}return savedFetch(url);};
 const mount=async(editor,site)=>{const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},site,tier:'low',bake:false});};
 let v,e;
 try{
  v=await mount(false,{lat:-35,lon:150,source:'site'});e=await mount(true,{lat:-35,lon:150,source:'site'});
  await new Promise(r=>setImmediate(r));assert.equal(reads,2,'one shared weather/season request per mount');
  v.setClock('2026-01-15T12:00:00Z');e.setClock('2026-01-15T12:00:00Z');
  assert.equal(v.season.latitude,-35);assert.equal(v.season.presence,1);assert.equal(v.season.dormancy,.71);assert.equal(v.season.avgTempC,9);
  assert.equal(e.season.neutral,true);assert.equal(e.season.dormancy,0);
  for(const preview of ['spring','summer','autumn','winter']){v.setSeasonPreview(preview);assert.equal(v.state.seasonPreview,preview);assert.equal(v.season.preview,preview);assert.ok(v.seasonPreviewDeadline()>Date.now());}
  assert.equal(v.season.dormancy,1);assert.equal(v.seasons.uniforms.seasonFoliage.value.x,0);
  v.setWeatherPreview('snow');assert.equal(v.season.preview,'winter');assert.equal(v.weather.preview,'snow');
  const saved=v.saveView();v.setTime('now');assert.equal(v.state.seasonPreview,null);assert.equal(v.season.dormancy,.71);assert.equal(v.weather.preview,null);
  v.restoreView(saved);assert.equal(v.state.seasonPreview,null);assert.equal(v.season.preview,null);
  const {mountLighting}=await import(file('static/twin/editor/lighting.js'));
  const host=new Element();for(const name of ['day','night','now','unlit','live']){const b=new Element('button');b.dataset.editorLighting=name;host.append(b);}
  const lighting=mountLighting(e,host,{storage:{getItem:()=>null,setItem(){}}});
  await click(host.querySelector('[data-editor-lighting="live"]'));assert.equal(e.season.neutral,false);assert.equal(e.season.dormancy,.71);
  lighting.select('day');assert.equal(e.season.neutral,true);assert.equal(e.season.presence,1);assert.equal(e.season.dormancy,0);
  v.setSite({source:'default'});v.setClock('2026-01-15T12:00:00Z');assert.equal(v.season.latitude,40);assert.equal(v.season.presence,0);
 }finally{v?.dispose();e?.dispose();globalThis.fetch=savedFetch;location.search=prior;}
});
finish();
"""

TREE_DRIVER = TREE_PREFIX + r"""
const THREE=await import('three'),EZ=await import('@dgreenheck/ez-tree');
const S=await import(file('static/twin/sky/seasons.js'));
const {presetTree,buildYard}=await import(file('static/twin/twin_yard.js'));
const {installPlantWind}=await import(file('static/twin/sky/wind.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const compile=(m,kind='standard')=>{const shader={uniforms:{},vertexShader:THREE.ShaderLib[kind].vertexShader,fragmentShader:THREE.ShaderLib[kind].fragmentShader};m.onBeforeCompile(shader,{});return shader;};
const dispose=group=>group.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});
await test('execute leaf colour and alpha test from the installed GLSL through a year',async()=>{
 const {group}=await buildYard({buildings:[],site:{planting:[{id:'oak',preset:'Oak Small',height:12,at:[0,0],seed:7}]}},{materials:{}},'high');
 const scene=new THREE.Scene();scene.add(group);const seasons=S.installSeasons(scene);seasons.prepare();
 let mesh;group.traverse(o=>{if(o.material?.userData.seasonFoliage)mesh=o;});const shader=compile(mesh.material);
 const body=shader.fragmentShader.match(/float leafLuminance[\s\S]*?diffuseColor\.rgb\*=mix\([^;]+;/)[0]
  .replace(/\b(?:float|vec3) (\w+)=/g,'let $1=').replace(/diffuseColor\.rgb/g,'color')
  .replace(/vSeasonLeaf\.y/g,'hue').replace(/seasonFoliage\.y/g,'autumn').replace(/seasonFoliage\.z/g,'spring')
  .replace(/leafAutumn\*=([^;]+);/,'leafAutumn=mul(leafAutumn,$1);').replace(/color\*=([^;]+);/,'color=mul(color,$1);');
 const vec3=(...v)=>v.length===1?[v[0],v[0],v[0]]:v,dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
 const mul=(a,b)=>a.map((v,i)=>v*(Array.isArray(b)?b[i]:b));
 const mix=(a,b,t)=>a.map((v,i)=>v+(b[i]-v)*t);
 const colour=new Function('color','hue','autumn','spring','vec3','dot','max','mix','mul',body+'return color;');
 const leafTest=shader.fragmentShader.match(/if\(vSeasonLeaf\.x>=seasonFoliage\.x\)discard;/)[0].replace('vSeasonLeaf.x','threshold').replace('seasonFoliage.x','presence').replace('discard;','return false;');
 const present=new Function('threshold','presence',leafTest+'return true;');
 const attr=mesh.geometry.attributes.seasonLeaf,counts=[];
 for(const day of ['2026-01-15','2026-04-05','2026-04-15','2026-04-26','2026-07-15','2026-10-23','2026-11-09','2026-11-16']){
  const s=S.seasonState(new Date(day),40);counts.push(Array.from({length:attr.count},(_,i)=>present(attr.getX(i),s.presence)).filter(Boolean).length);
  for(const hue of [0,.25,.5,.75,.999]){
   const rgb=colour([.03,.14,.015],hue,s.autumn,s.spring,vec3,dot,Math.max,mix,mul);
   assert.ok(rgb.every(v=>Number.isFinite(v)&&v>=0));
   if(day==='2026-07-15')assert.deepEqual(rgb,[.03,.14,.015]);
   if(day==='2026-10-23')assert.ok(rgb[0]>.03,'autumn gains yellow/orange/red');
  }
 }
 assert.equal(counts[0],0);assert.equal(counts[1],0);assert.ok(counts[2]>0&&counts[2]<counts[3]);
 assert.equal(counts[3],attr.count);assert.equal(counts[4],attr.count);assert.equal(counts[5],attr.count);
 assert.ok(counts[6]>0&&counts[6]<attr.count);assert.equal(counts[7],0);
 dispose(group);seasons.dispose();
});
await test('every actual EZ-Tree preset is tagged; each generated leaf has one stable threshold on both planes',()=>{
 assert.deepEqual(Object.keys(S.PRESET_SEASONS).sort(),Object.keys(EZ.TreePreset).sort());
 for(const preset of Object.keys(EZ.TreePreset)){
  const a=presetTree(preset,7),b=presetTree(preset,7),c=presetTree(preset,8),attr=a.leavesMesh.geometry.attributes.seasonLeaf;
  assert.equal(attr.count,a.leavesMesh.geometry.attributes.position.count,preset);
  assert.deepEqual(attr.array,b.leavesMesh.geometry.attributes.seasonLeaf.array);
  assert.ok(attr.array.every(v=>v>=0&&v<1));
  const verticesPerLeaf=a.options.leaves.billboard==='double'?8:4;
  for(let i=0;i<attr.count;i+=verticesPerLeaf)for(let j=1;j<verticesPerLeaf&&i+j<attr.count;j++)assert.equal(attr.getX(i),attr.getX(i+j),preset+' one leaf');
  const thresholds=new Set(Array.from({length:attr.count},(_,i)=>attr.getX(i)));
  assert.ok(thresholds.size>1,preset+' individual leaves');
  assert.equal(a.userData.seasonKind,preset.startsWith('Pine')?'evergreen':'deciduous');
  dispose(a);dispose(b);dispose(c);
 }
 for(const kind of ['pine','spruce','fir','juniper','boxwood','holly'])assert.equal(S.plantSeason('Bush 1',kind),'evergreen');
 for(const kind of ['tree','shrub','plant','oak','ash','aspen','birch','maple'])assert.equal(S.plantSeason('Bush 1',kind),'deciduous');
});
await test('real oak, shrub, pine, evergreen kind, branches and imported material; wind/snow/clones share stable hooks',async()=>{
 const plan={buildings:[],site:{planting:[
  {id:'oak-a',preset:'Oak Small',height:12,at:[0,0],seed:7},{id:'oak-b',preset:'Oak Small',height:12,at:[10,0],seed:7},
  {id:'bush',preset:'Bush 1',height:3,at:[20,0]},{id:'pine',preset:'Pine Small',height:12,at:[30,0]},
  {id:'boxwood',kind:'boxwood',preset:'Bush 1',height:3,at:[40,0]}]}};
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true}),scene=new THREE.Scene();scene.add(group);
 const imported=new THREE.MeshStandardMaterial({name:'imported tree'}),importedObject=new THREE.Mesh(new THREE.BoxGeometry(),imported);importedObject.userData.placedPlant=true;scene.add(importedObject);
 const wind=installPlantWind(scene),snow=installWeatherSurface(scene),seasons=S.installSeasons(scene);
 wind.prepare();snow.prepare();seasons.prepare();
 const records=[];let foliage=0,branches=0;
 for(const plant of group.children){
  plant.traverse(o=>{
   if(!o.isMesh)return;const m=o.material,shader=compile(m),deciduous=plant.userData.seasonKind==='deciduous'&&m.userData.plantWind==='leaves';
   assert.equal(!!shader.uniforms.seasonFoliage,deciduous);
   if(m.userData.plantWind==='branches'){branches++;assert.ok(!shader.fragmentShader.includes('vSeasonLeaf'));}
   if(deciduous){
    foliage++;assert.ok(shader.fragmentShader.includes('vSeasonLeaf.x>=seasonFoliage.x'));assert.ok(shader.vertexShader.includes('plantHeight'));
    assert.equal(shader.uniforms.weatherSurface,snow.uniforms.weatherSurface);
    assert.ok(o.customDepthMaterial&&o.customDistanceMaterial,'winter shadows drop the same leaves');
    for(const [shadow,kind]of [[o.customDepthMaterial,'depth'],[o.customDistanceMaterial,'distance']])assert.ok(compile(shadow,kind).fragmentShader.includes('vSeasonLeaf.x>=seasonFoliage.x'));
    const clone=m.clone();const object=new THREE.Mesh(o.geometry,clone);scene.add(object);seasons.prepare();wind.prepare();snow.prepare();
    assert.equal(clone.customProgramCacheKey(),m.customProgramCacheKey());assert.equal(compile(clone).uniforms.seasonFoliage,seasons.uniforms.seasonFoliage);
   }
   records.push({m,shader,key:m.customProgramCacheKey(),version:m.version,geometry:o.geometry,attribute:o.geometry.attributes.seasonLeaf?.array.slice()});
  });
 }
 assert.equal(foliage,3);assert.equal(branches,5);assert.ok(!compile(imported).uniforms.seasonFoliage);
 const hue=id=>{const p=group.children.find(o=>o.userData.pieceId===id);let result;p.traverse(o=>{if(o.material?.userData.plantWind==='leaves')result=o.geometry.attributes.seasonLeaf.getY(0);});return result;};
 assert.notEqual(hue('oak-a'),hue('oak-b'),'same seed, distinct stable per-tree autumn hue');
 for(const preview of ['spring','summer','autumn','winter']){
  seasons.update(S.seasonState(new Date('2026-07-15'),40,{}, {preview}));
  for(const r of records){assert.equal(r.m.customProgramCacheKey(),r.key);assert.equal(r.m.version,r.version);assert.equal(compile(r.m).fragmentShader,r.shader.fragmentShader);if(r.attribute)assert.deepEqual(r.geometry.attributes.seasonLeaf.array,r.attribute);}
 }
 assert.equal(seasons.uniforms.seasonFoliage.value.x,0);assert.ok(!THREE.ShaderChunk.lights_pars_begin.includes('season'));
 dispose(group);seasons.dispose();wind.dispose();snow.dispose();
});
await test('low cards retain one per-card threshold and hue after batching; no wind; evergreen unchanged',async()=>{
 const plan={buildings:[],site:{planting:[{id:'a',preset:'Oak Small',height:10,at:[0,0],seed:7},{id:'b',preset:'Pine Small',height:10,at:[20,0],seed:8}]}};
 const {group}=await buildYard(plan,{materials:{}},'low',{viewing:true}),scene=new THREE.Scene();scene.add(group);
 const seasons=S.installSeasons(scene),wind=installPlantWind(scene,{tier:'low'});seasons.prepare();wind.prepare();
 for(const plant of group.children){
  const meshes=[];plant.traverse(o=>{if(o.isMesh)meshes.push(o);});assert.equal(meshes.length,1,'existing card batching retained');
  const mesh=meshes[0],attr=mesh.geometry.attributes.seasonLeaf;assert.equal(attr.count,mesh.geometry.attributes.position.count);
  assert.equal(new Set(Array.from({length:attr.count},(_,i)=>attr.getX(i))).size,2,'crossed cards have separate thresholds');
  const shader=compile(mesh.material);assert.equal(!!shader.uniforms.seasonFoliage,plant.userData.seasonKind==='deciduous');assert.ok(!shader.uniforms.plantWind);
 }
 dispose(group);seasons.dispose();wind.dispose();
});
finish();
"""

CENSUS_PREFIX = CLOUD_DRIVER.split("await test('lazy CPU texels")[0].replace(YARD_PREFIX, TREE_PREFIX, 1)
CENSUS_DRIVER = CENSUS_PREFIX + r"""
const S=await import(file('static/twin/sky/seasons.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {installPlantWind}=await import(file('static/twin/sky/wind.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
await test('paver joint blades and lawn share the dormancy uniform and metre patch field',async()=>{
 const {PAVER_DEFAULTS}=await import(file('static/twin/paver_layout.js'));
 const plan={buildings:[],site:{lot:[[0,0],[40,0],[40,30],[0,30]],hardscape:[{id:'path',kind:'path',points:[[5,15],[35,15]],width:5,pavers:{...PAVER_DEFAULTS}}]}};
 const {group}=await buildYard(plan,{materials:{}},'high'),scene=new THREE.Scene();group.scale.setScalar(.3048);scene.add(group);
 const seasons=S.installSeasons(scene);seasons.prepare();const grass=group.userData.grass;
 assert.ok(grass.jointInstances>0);assert.ok(grass.instances>grass.jointInstances);
 const flags=grass.mesh.geometry.attributes.grassJoint.array;assert.equal(Array.from(flags).filter(v=>v===1).length,grass.jointInstances);
 let lawns=0;group.traverse(o=>{if(!o.material?.userData.seasonLawn)return;const shader=assemble(o.material,new Renderer());assert.equal(shader.uniforms.seasonDormancy,seasons.uniforms.seasonDormancy);assert.ok(shader.fragmentShader.includes(S.LAWN_GLSL));lawns++;});
 assert.ok(lawns>=2);for(const dormancy of [0,.5,1]){seasons.update({presence:1,autumn:0,spring:0,dormancy});assert.equal(assemble(grass.mesh.material,new Renderer()).uniforms.seasonDormancy.value,dormancy);}
 group.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});seasons.dispose();
});
await test('actual GLSL dormancy curve and tint: green identity, straw luminance, monotonic patches and blade/lawn agreement',()=>{
 const mix=(a,b,t)=>a+(b-a)*t,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
 const smoothstep=(a,b,v)=>{const t=clamp((v-a)/(b-a),0,1);return t*t*(3-2*t);};
 const fn=S.LAWN_GLSL.match(/float seasonDry\(([^)]*)\) \{([\s\S]*?)\n\}/);
 const dry=new Function('smoothstep','clamp',`return (${fn[1].replace(/float /g,'')})=>{${fn[2]}}`)(smoothstep,clamp);
 for(let threshold=0;threshold<=1;threshold+=.01){
  assert.equal(dry(0,threshold),0);assert.equal(dry(1,threshold),1);
  let previous=0;for(let d=0;d<=1;d+=.01){const amount=dry(d,threshold);assert.ok(Number.isFinite(amount)&&amount>=previous&&amount<=1);previous=amount;}
 }
 assert.ok(dry(.5,.2)>dry(.5,.8),'one world cell turns ahead of another');
 const lum=rgb=>rgb.reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
 for(const green of [[.025,.12,.01],[0,0,0],[.1,.3,.05]]){
  const straw=[.42,.34,.2].map(v=>v*lum(green)/.3469);
  assert.ok(Math.abs(lum(straw)-lum(green))<1e-12);assert.ok(straw.every(Number.isFinite));
 }
 const scene=new THREE.Scene(),lawn=new THREE.MeshStandardMaterial();lawn.userData.seasonLawn=true;
 const blades=grassMaterial(lawn),lawnMesh=new THREE.Mesh(new THREE.PlaneGeometry(),lawn),bladeMesh=new THREE.InstancedMesh(new THREE.BoxGeometry(),blades,1);
 scene.add(lawnMesh,bladeMesh);const seasons=S.installSeasons(scene);seasons.prepare();
 const a=assemble(lawn,new Renderer()),b=assemble(blades,new Renderer());
 assert.equal(a.uniforms.seasonDormancy,b.uniforms.seasonDormancy);
 for(const source of [a.fragmentShader,b.fragmentShader])assert.ok(source.includes(S.LAWN_GLSL));
 assert.ok(b.vertexShader.includes('vSeasonWorld=grassWorld.xz;'));
 assert.ok(b.fragmentShader.indexOf('diffuseColor.rgb *= lawn * mix')<b.fragmentShader.indexOf('diffuseColor.rgb=seasonLawn'));
});
await test('built real household r187 census: seasons stay on vegetation; keys and sources never follow date or previews',async()=>{
 for(const tier of ['high','low']){
  const renderer=new Renderer(),scene=new THREE.Scene();renderer.toneMapping=THREE.ACESFilmicToneMapping;
  scene.environment=new THREE.Texture();renderer.shadowMap.enabled=tier==='high';renderer.shadowMap.type=THREE.PCFShadowMap;
  const haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),weather=installWeatherSurface(scene),wind=installPlantWind(scene,{tier});
  const model=buildTwin(input.plan,{materials:{}},tier,{viewing:true});scene.add(model.root);
  const {group}=await buildYard(input.plan,{materials:{}},tier,{viewing:true});group.scale.setScalar(.3048);scene.add(group);
  const view={plan:input.plan,scene,roomLights:[],camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},renderer3:renderer};view.camera.position.set(0,30,30);
  const viewing=createViewing(view,model,()=>0,()=>{});
  // A material imported for a tree is deliberately untagged, even if named leaves.
  const imported=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshStandardMaterial({name:'imported tree leaves'}));scene.add(imported);
  haze.prepare();shadow.prepare();wind.prepare();weather.prepare();
  const cache=programs(renderer),lights=makeLights();lights.directional=[{},{}];lights.directionalShadowMap=tier==='high'?[{}]:[];lights.hemi=[{}];
  const rows=[],seen=new Set();scene.traverse(o=>{
   if(!o.isMesh||Array.isArray(o.material)||!o.material.isMeshStandardMaterial)return;
   const key=o.material.uuid+':'+!!o.isInstancedMesh;if(seen.has(key))return;seen.add(key);
   rows.push({object:o,material:o.material,base:programSource(renderer,cache,scene,o,lights)});
  });
  const seasons=S.installSeasons(scene);seasons.prepare();
  const totals=new Map();let changed=0;
  for(const row of rows){
   const m=row.material,source=programSource(renderer,cache,scene,row.object,lights),before=uniformBudget(row.base[2]),after=uniformBudget(source[2]);
   const category=m.userData.seasonFoliage?(m.name.startsWith('plant card')?'card':'leaves'):m.userData.seasonLawn?(m.userData.grassUniforms?'blades':m.name==='edge grass'?'edge grass':'lawn'):m.userData.plantWind==='branches'?'branches':'other';
   const expected=m.userData.seasonFoliage||m.userData.seasonLawn?1:0;
   assert.equal(after.vectors-before.vectors,expected,category+' '+m.name);assert.deepEqual(after.samplers,before.samplers);
   assert.ok(after.vectors<224,category+' '+after.vectors);assert.ok(after.samplers.length<=16);
   const uniforms=Object.keys(source.shader.uniforms).filter(n=>n.startsWith('season'));
   assert.deepEqual(uniforms,m.userData.seasonFoliage?['seasonFoliage']:m.userData.seasonLawn?['seasonDormancy']:[]);
   if(!expected){assert.equal(source[2],row.base[2]);assert.equal(source[1],row.base[1]);}else changed++;
   const t=totals.get(category)||{count:0,min:Infinity,max:0,samplers:0};t.count++;t.min=Math.min(t.min,after.vectors);t.max=Math.max(t.max,after.vectors);t.samplers=Math.max(t.samplers,after.samplers.length);totals.set(category,t);
   row.source=source;row.version=m.version;row.customKey=m.customProgramCacheKey();
  }
  assert.ok(changed>0);assert.ok(totals.has('lawn'));assert.ok(totals.has(tier==='high'?'leaves':'card'));
  if(tier==='high')assert.ok(totals.has('blades'));
  for(const preview of ['spring','summer','autumn','winter',null])for(const dormancy of [0,.5,1]){
   seasons.update(S.seasonState(new Date('2026-01-15'),40,{lawn:{dormancy,grass_type:'warm',source:'history'}},{preview}));
   for(const row of rows){assert.equal(row.material.customProgramCacheKey(),row.customKey);assert.equal(row.material.version,row.version);}
  }
  // Assemble again after every state transition, with the actual r187 key builder.
  for(const row of rows){const after=programSource(renderer,cache,scene,row.object,lights);assert.equal(after.key,row.source.key);assert.equal(after[1],row.source[1]);assert.equal(after[2],row.source[2]);}
  console.log('SEASON_CENSUS',JSON.stringify({fixture:input.label,tier,programMaterials:rows.length,totals:Object.fromEntries(totals)}));
  viewing.dispose();seasons.dispose();weather.dispose();wind.dispose();shadow.dispose();haze.dispose();
  group.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});
 }
});
await test('heaviest pool stress r187 source is unchanged: 224 fragment vectors, 16 samplers',()=>{
 const renderer=new Renderer(),scene=new THREE.Scene(),haze=installStageHaze(scene,{}),shadow=installCloudShadow(scene,{uniforms:createCloudUniforms()}),weather=installWeatherSurface(scene);
 renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFShadowMap;scene.environment=new THREE.Texture();
 const lights=makeLights();lights.directional=[{},{}];lights.directionalShadowMap=[{}];lights.point=Array.from({length:4},()=>({}));lights.pointShadowMap=[{},{}];lights.spot=[{},{}];lights.spotShadowMap=[{}];lights.rectArea=[{}];lights.hemi=[{}];
 const source=new THREE.MeshPhysicalMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture(),transparent:true,opacity:.4});
 const body={polygon:[[0,0],[20,0],[20,20],[0,20]],height:0,sources:[{}]},simulation=createWaterSimulation(body);
 const water=surfaceMaterial(source,body,{tier:'high',simulation});reflectionMaterial(water.material,'water','pool');
 const object=new THREE.Mesh(new THREE.BoxGeometry(),water.material);object.receiveShadow=true;scene.add(object);haze.prepare();shadow.prepare();weather.prepare();
 const cache=programs(renderer),before=programSource(renderer,cache,scene,object,lights),seasons=S.installSeasons(scene);seasons.prepare();
 for(const preview of ['spring','summer','autumn','winter']){
  seasons.update(S.seasonState(new Date(),40,{}, {preview}));const after=programSource(renderer,cache,scene,object,lights);
  assert.equal(after[1],before[1]);assert.equal(after[2],before[2]);assert.equal(after.key,before.key);
 }
 const budget=uniformBudget(before[2]);assert.equal(budget.vectors,224);assert.equal(budget.samplers.length,16);
 console.log('SEASON_STRESS',JSON.stringify(budget));simulation.dispose();seasons.dispose();weather.dispose();shadow.dispose();haze.dispose();
});
finish();
"""

IMPORT_DRIVER = TREE_PREFIX + r"""
// Exercise the real import/normalise/cache/yard path; only binary decoding is
// replaced with an in-memory model. There is no network or browser context.
registerHooks({resolve(spec,ctx,next){
 if(spec==='three/addons/loaders/GLTFLoader.js')return {shortCircuit:true,url:data(`
 import {Group,Mesh,BoxGeometry,MeshStandardMaterial} from '${three}';
 export class GLTFLoader {
  setResourcePath(){return this;}
  async loadAsync(){const scene=new Group();scene.add(new Mesh(new BoxGeometry(2,8,2),new MeshStandardMaterial({name:'leaves',color:'#446622',alphaTest:.5})));return {scene};}
 }`)};
 return next(spec,ctx);
}});
const THREE=await import('three');
const {rememberImport}=await import(file('static/twin/twin_library.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const S=await import(file('static/twin/sky/seasons.js'));
await test('imported tree through the real yard model loader keeps its colour, geometry and program across all seasons',async()=>{
 window.location=location;
 rememberImport({id:'import-season-tree',kind:'plant',files:{'tree.glb':{}},model:'tree.glb'});
 const plan={buildings:[],site:{planting:[{id:'imported',asset:'import-season-tree',kind:'tree',height:12,at:[0,0]}]}};
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true}),scene=new THREE.Scene();scene.add(group);
 const meshes=[];group.traverse(o=>{if(o.isMesh)meshes.push(o);});assert.ok(meshes.length,'the imported tree really loaded');
 const records=meshes.map(o=>({object:o,material:o.material,colour:o.material.color.toArray(),positions:o.geometry.attributes.position.array.slice(),key:o.material.customProgramCacheKey()}));
 const seasons=S.installSeasons(scene);
 for(const preview of ['spring','summer','autumn','winter']){
  seasons.update(S.seasonState(new Date(),40,{}, {preview}));
  for(const r of records){assert.equal(r.material.customProgramCacheKey(),r.key);assert.deepEqual(r.material.color.toArray(),r.colour);assert.deepEqual(r.object.geometry.attributes.position.array,r.positions);assert.ok(!r.material.userData.seasonFoliage);assert.ok(!r.material.userData.seasonLawn);}
 }
 group.traverse(o=>{o.geometry?.dispose();for(const m of [].concat(o.material||[]))m.dispose();});seasons.dispose();
});finish();
"""


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    household = flatten(assemble(fixture)[0])
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': household}, timeout=180)
    print(output)
    failed = bool(code)
    code, output = run_node(TREE_DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    failed |= bool(code)
    code, output = run_node(CENSUS_DRIVER, {'root': ROOT.as_posix(), 'plan': household, 'label': 'household'}, timeout=240)
    print(output)
    failed |= bool(code)
    code, output = run_node(IMPORT_DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(1 if failed or code else 0)
