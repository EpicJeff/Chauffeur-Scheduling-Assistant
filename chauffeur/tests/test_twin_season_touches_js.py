"""Seasonal particles and shafts: executed Node paths, real household, no browser."""
import json
from pathlib import Path
import sys

from twin_editor_dom import run_node
from test_twin_tree_once_js import PREFIX as TREE_PREFIX
from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER
from test_twin_reflection_probes_js import DRIVER as REFLECTION_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = TREE_PREFIX + r"""
const THREE=await import('three');
const T=await import(file('static/twin/sky/season_touches.js'));
const {seasonState}=await import(file('static/twin/sky/seasons.js'));
const {lightShaftState,createPost}=await import(file('static/twin/post.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const day=s=>new Date(s+'T12:00:00Z'),summer=seasonState(day('2026-07-15'),40),autumn=seasonState(day('2026-10-25'),40);
const warm={temperatureC:18,precip:'none',rate:0,windMps:8,windToDeg:90};
const conditions={date:day('2026-07-15'),sunAltDeg:-5};
await test('generated household sources retain actual leaf cards, weights, maps and hues',async()=>{
 const {buildYard}=await import(file('static/twin/twin_yard.js'));
 const yard=(await buildYard(input.plan,{materials:{}},'high',{viewing:true})).group;
 yard.scale.setScalar(.3048);
 const p=T.createSeasonTouches(new THREE.Scene(),{tier:'high',random:()=>.417});p.setPlan(input.plan);
 const eye=new THREE.PerspectiveCamera(100,1,.1,2000);eye.position.set(0,100,160);eye.lookAt(0,0,0);eye.updateMatrixWorld();
 p.update(0,autumn,warm,eye,{plants:yard,target:new THREE.Vector3(),extent:1000});
 // Weight follows crown width (sqrt of the footprint), owner 2026-11-19.
 const sources=p.info().sources;assert.ok(sources.length>5);const total=sources.reduce((n,s)=>n+Math.sqrt(s.area),0);
 for(const s of sources){
  assert.ok(s.count>0);assert.equal(s.data.positions.length,s.count*3);assert.ok(s.texture?.isTexture);
  assert.equal(s.hue,s.object.userData.seasonHue);assert.ok(Math.abs(s.weight-Math.sqrt(s.area)/total)<1e-10);
 }
 const shrubs=sources.filter(s=>s.object.userData.pieceId.startsWith('cmp-shrub')),trees=sources.filter(s=>s.object.userData.pieceId.startsWith('cmp-tree'));
 assert.ok(Math.min(...trees.map(s=>s.weight))>Math.max(...shrubs.map(s=>s.weight))*3,'large trees shed much more than individual small shrubs');
 const seen=new Set(),spawned=new Map();
 for(let i=1;i<=400;i++){
  p.update(i,{...autumn,autumn:1,presence:.5},{...warm,windMps:0},eye,{plants:yard,target:new THREE.Vector3(),extent:1000});
  for(const leaf of [...p.info().falling,...p.info().resting])if(!seen.has(leaf.id)){
   seen.add(leaf.id);spawned.set(leaf.source,(spawned.get(leaf.source)||0)+1);
  }
 }
 assert.ok(seen.size>300);
 for(const source of sources){
  const observed=(spawned.get(source.object)||0)/seen.size;
  assert.ok(Math.abs(observed-source.weight)<.065,'observed spawn frequency follows generated canopy area');
 }
 console.log('household leaf weights',JSON.stringify(sources.map(s=>({id:s.object.userData.pieceId,preset:s.object.userData.seasonPreset,count:s.count,area:s.area,weight:s.weight,hue:s.hue,texture:s.texture.uuid}))));
 p.dispose();
});
await test('exact tier budgets, phenology, weather and hemispheres; preview is night only',()=>{
 for(const [tier,leaves] of Object.entries({low:60,medium:100,high:150,max:240})){
  assert.equal(T.seasonTouchCounts(tier,autumn,warm,conditions).leaves,leaves);
  assert.equal(T.seasonTouchCounts(tier,summer,warm,conditions).fireflies,tier==='low'?25:60);
 }
 for(const s of [seasonState(day('2026-04-15'),40),summer,seasonState(day('2026-12-01'),40),{...autumn,neutral:true}])
  assert.equal(T.seasonTouchCounts('high',s,warm,conditions).leaves,0);
 for(const [weather,opts] of [[{...warm,temperatureC:17.99},conditions],[{...warm,temperatureC:null},conditions],
  [{...warm,precip:'rain',rate:.1},conditions],[warm,{...conditions,sunAltDeg:-4}],
  [warm,{...conditions,date:day('2026-09-01')}],[warm,{...conditions,enabled:false}]])
  assert.equal(T.seasonTouchCounts('high',summer,weather,opts).fireflies,0);
 const south={...summer,latitude:-35};
 assert.equal(T.seasonTouchCounts('high',south,warm,{...conditions,date:day('2026-01-15')}).fireflies,60);
 assert.equal(T.seasonTouchCounts('high',south,warm,conditions).fireflies,0);
 const preview={...summer,preview:'summer'};
 assert.equal(T.seasonTouchCounts('high',preview,{}, {...conditions,date:day('2026-12-15')}).fireflies,60);
 assert.equal(T.seasonTouchCounts('high',preview,warm,{...conditions,sunAltDeg:0}).fireflies,0);
});
const plan={site:{lot:[[-100,-100],[100,-100],[100,100],[-100,100]],beds:[{polygon:[[25,25],[45,25],[45,45],[25,45]]}],
 pool:{polygon:[[-40,20],[-20,20],[-20,40],[-40,40]],features:[{kind:'spa',polygon:[[-20,20],[-10,20],[-10,30],[-20,30]]}]}},
 buildings:[{id:'rotated',position:[8,-4],rotation:35,levels:[{id:'g',elevation:0,ceiling:10}],rooms:[{id:'r',level:'g',polygon:[[-20,-15],[20,-15],[20,15],[-20,15]]}]}]};
await test('lawn sampler excludes rotated buildings, pool, spa, beds, edges and missing lawn',()=>{
 const sample=T.createLawnSampler(plan);
 assert.equal(sample(8*.3048,4*.3048),null);assert.equal(sample(30*.3048,-30*.3048),null);
 assert.equal(sample(-30*.3048,-30*.3048),null);assert.equal(sample(-15*.3048,-25*.3048),null);
 assert.equal(sample(101*.3048,0),null);assert.equal(sample(NaN,0),null);
 assert.equal(T.createLawnSampler({})(0,0),null);
 assert.ok(sample(70*.3048,0));
 for(const household of [plan,input.plan]){
  const safe=T.createLawnSampler(household);let accepted=0;
  const p=T.createSeasonTouches(new THREE.Scene(),{tier:'max',random:()=>.417});p.setPlan(household);
  const eye=new THREE.PerspectiveCamera(60,1,.1,1000);eye.position.set(0,25,35);eye.lookAt(0,0,0);eye.updateMatrixWorld();
  for(let frame=0;frame<100;frame++){
   p.update(frame*.1,summer,warm,eye,{...conditions,target:new THREE.Vector3(),lawn:true});
   const o=p.objects.fireflies,a=o.geometry.attributes.touchPosition;
   for(let i=0;i<o.geometry.instanceCount;i++){assert.ok(safe(a.getX(i),a.getZ(i)),'every moving firefly remains on lawn');accepted++;}
  }
  assert.ok(accepted>0,'sample actual lawn');p.dispose();
 }
});
await test('leaf landing accepts lawn, beds, paving and deck heights; rejects water, indoor, covered and roof',async()=>{
 const {createSkyCover}=await import(file('static/twin/sky/sky_cover.js'));
 const base=createSkyCover(plan),cover={blocked:(x,y,z)=>x>20||base.blocked(x,y,z)};
 const sample=T.createLeafLandingSampler(plan,new Map(),cover);
 assert.equal(sample(-30*.3048,-30*.3048),null);assert.equal(sample(-15*.3048,-25*.3048),null);
 assert.equal(sample(8*.3048,4*.3048),null);assert.equal(sample(25,0),null);
 for(const [x,z,height] of [[0,20,0],[30*.3048,-30*.3048,.12*.3048],[18,0,0]]){
  const hit=sample(x,z);assert.ok(hit);assert.ok(Math.abs(hit[1]-height-.006)<1e-8,'use the visible bed soil top, not buried terrain');
 }
 const p={site:{hardscape:[{polygon:[[0,0],[10,0],[10,10],[0,10]],elevation:2}]},buildings:[{id:'b',levels:[{id:'l',elevation:0}],porches:[{polygon:[[12,0],[18,0],[18,5],[12,5]],floor:3}]}]};
 const hit=T.createLeafLandingSampler(p)(5*.3048,-5*.3048);assert.ok(Math.abs(hit[1]-2.3*.3048-.006)<1e-8);
 const deck=T.createLeafLandingSampler(p)(15*.3048,-2*.3048);assert.ok(Math.abs(deck[1]-3*.3048-.006)<1e-8);
 const roofs=new Map([['b',{sections:[{kind:'flat',rect:[12,0,18,5],plate:12}]}]]);
 assert.equal(T.createLeafLandingSampler(p,roofs)(15*.3048,-2*.3048),null);
});
await test('real leaf cards spawn inside canopies, scatter uniquely, collect eight minutes and keep fixed keys',async()=>{
 const {presetTree}=await import(file('static/twin/twin_yard.js'));
 const scene=new THREE.Scene(),root=new THREE.Group();scene.add(root);
 const tree=presetTree('Oak Small',1);Object.assign(tree.userData,{seasonKind:'deciduous',yardPlantIndex:0,seasonHue:.2});
 // Drop is per crown width now; a crown this wide drops enough to cycle the 200-leaf ring.
 tree.scale.setScalar(.3);root.add(tree);
 const pine=presetTree('Pine Small',2);pine.userData.seasonKind='evergreen';root.add(pine);
 const p=T.createSeasonTouches(scene,{tier:'low',random:()=>.417});p.setPlan({site:{lot:[[-200,-200],[200,-200],[200,200],[-200,200]],planting:[{height:25}]}});
 const eye=new THREE.PerspectiveCamera(60,1,.1,1000);eye.position.set(0,15,30);eye.lookAt(0,3,0);eye.updateMatrixWorld();
 const opts={...conditions,target:new THREE.Vector3(),plants:root},drop={...autumn,presence:.5,autumn:1};
 p.update(0,drop,{...warm,visibilityM:300},eye,opts);assert.equal(p.uniforms.touchExtinction.value,3.912/300,'own leaf program follows the same camera fog');
 const keys=Object.values(p.objects).map(o=>[o.material.customProgramCacheKey(),o.material.version]);
 const paths=new Map();let settled=0;
 for(let i=0;i<1000;i++){
  p.update(i,drop,{...warm,windMps:0},eye,opts);
  assert.equal(p.uniforms.touchExtinction.value,0);
  assert.ok(p.info().falling.length<=60);assert.ok(p.info().resting.length<=200);
  for(const leaf of p.info().falling){
   const expected=new THREE.Vector3().fromArray(tree.seasonLeaves.positions,leaf.sourceIndex*3).applyMatrix4(tree.matrixWorld);
   assert.ok(expected.distanceTo(new THREE.Vector3(...leaf.origin))<1e-8,'spawn is an actual generated leaf centre');
   assert.equal(leaf.batch.texture,tree.seasonLeaves.texture);
   paths.set(leaf.id,JSON.stringify([leaf.axis,leaf.spin,leaf.phase,leaf.flutter,leaf.drag,leaf.frequency]));
  }
  for(const leaf of p.info().resting){assert.equal(leaf.position[1],.006);settled++;}
 }
 assert.ok(settled>0);assert.ok(paths.size>50);assert.equal(new Set([...paths.values()].slice(0,50)).size,50);
 assert.equal(p.info().resting.length,200,'fixed ring overwrites oldest leaves');
 const oldest=Math.min(...p.info().resting.map(l=>l.born));assert.ok(oldest>0);
 assert.equal(p.uniforms.touchAnchor.value.x,0);assert.ok(p.uniforms.touchExtent.value>=18);
 for(let t=1080;t<=1130;t++)p.update(t,summer,{...warm,windMps:0},eye,opts);
 assert.equal(p.info().falling.length,0,'drain in-flight leaves before testing resting lifetime');
 assert.ok(p.info().resting.every(leaf=>leaf.autumn===1),'resting leaves retain their deposited autumn colour after the season changes');
 const resting=p.info().resting[0],born=resting.born;
 p.update(born+451,summer,{...warm,windMps:0},eye,opts);assert.ok(p.info().resting.includes(resting));
 const a=resting.batch.object.geometry.attributes.touchShape;
 assert.ok(Array.from({length:resting.batch.object.geometry.instanceCount},(_,i)=>a.getZ(i)).some(alpha=>alpha>0&&alpha<1),'last thirty seconds fade');
 p.update(born+480,summer,{...warm,windMps:0},eye,opts);assert.ok(!p.info().resting.includes(resting));
 p.update(2000,summer,warm,eye,opts);assert.equal(p.info().resting.length,0);
 p.update(2001,drop,warm,eye,{...opts,enabled:false});assert.ok(Object.values(p.objects).every(o=>!o.visible));
 assert.deepEqual(Object.values(p.objects).map(o=>[o.material.customProgramCacheKey(),o.material.version]),keys);
 for(const o of Object.values(p.objects)){assert.equal(o.castShadow,false);assert.equal(o.receiveShadow,false);assert.equal(o.material.isShaderMaterial,true);assert.equal(o.layers.isEnabled(1),false);const hits=[];o.raycast(null,hits);assert.equal(hits.length,0);}
 let freed=0;for(const o of Object.values(p.objects)){o.geometry.addEventListener('dispose',()=>freed++);o.material.addEventListener('dispose',()=>freed++);}
 p.dispose();p.dispose();assert.equal(freed,14);assert.equal(p.group.parent,null);
});
await test('all resting caps, six texture draws, reduced motion and gust re-tumbling',async()=>{
 const {presetTree}=await import(file('static/twin/twin_yard.js')),tree=presetTree('Bush 1',3),root=new THREE.Group();
 const textures=[];
 // Drop is per crown width now: size each source to a 6 m crown so six of them
 // drop fast enough to fill even the max tier's resting ring within 600 s.
 const ps=tree.seasonLeaves.positions;let x0=Infinity,x1=-Infinity;
 for(let i=0;i<ps.length;i+=3){x0=Math.min(x0,ps[i]);x1=Math.max(x1,ps[i]);}
 const crown=6/Math.max(x1-x0,1e-6);
 for(let i=0;i<7;i++){
  const source=new THREE.Group(),texture=tree.seasonLeaves.texture.clone();textures.push(texture);
  source.seasonLeaves={...tree.seasonLeaves,texture};source.scale.setScalar(crown);
  source.userData={seasonKind:'deciduous',seasonHue:i/7};root.add(source);
 }
 const eye=new THREE.PerspectiveCamera(60,1,.1,1000);eye.position.set(0,5,20);eye.lookAt(0,0,0);eye.updateMatrixWorld();
 const drop={...autumn,autumn:1,presence:.5},opts={plants:root,target:new THREE.Vector3()},calm={...warm,windMps:0};
 assert.equal(T.leafDropRate(summer),0);assert.equal(T.leafDropRate({...drop,presence:0}),0);
 assert.ok(T.leafDropRate(autumn)<T.leafDropRate(drop)*.1);
 for(const [tier,cap] of Object.entries({low:200,medium:320,high:480,max:760})){
  const p=T.createSeasonTouches(new THREE.Scene(),{tier,random:()=>.417});p.setPlan({});
  for(let t=0;t<=600;t++){
   p.update(t,drop,calm,eye,opts);assert.ok(p.info().resting.length<=cap);
   assert.ok(p.info().falling.length<={low:60,medium:100,high:150,max:240}[tier]);
   assert.ok(Object.values(p.objects).filter(o=>o.name!=='season-fireflies'&&o.visible).length<=6);
  }
  assert.equal(p.info().restCapacity,cap);assert.equal(p.info().resting.length,cap);
  assert.equal(p.info().sources.length,6,'seventh distinct texture waits for a free slot');
  const old=new Set(p.info().resting.map(l=>l.id));let lifted=false;
  for(let t=601;t<661;t++){
   p.update(t,summer,{...warm,windMps:12},eye,opts);
   lifted||=p.info().falling.some(l=>old.has(l.id));
  }
  assert.ok(lifted,'strong wind re-tumbles some resting leaves');
  const rest=p.info().resting.length;p.update(661,summer,calm,eye,{...opts,reduced:true});assert.ok(p.info().resting.length>=rest);
  for(let t=662;t<=730;t++)p.update(t,summer,calm,eye,opts);
  assert.equal(p.info().falling.length,0);
  p.update(1300,summer,calm,eye,opts);assert.equal(p.info().resting.length,0);p.dispose();
 }
 const normal=T.createSeasonTouches(new THREE.Scene(),{tier:'low',random:()=>.417}),slow=T.createSeasonTouches(new THREE.Scene(),{tier:'low',random:()=>.417});
 for(const p of [normal,slow])p.setPlan({});
 for(let i=0;i<50;i++){
  normal.update(i*.1,drop,calm,eye,opts);slow.update(i*.1,drop,calm,eye,{...opts,reduced:true});
 }
 assert.ok(slow.info().falling.length+slow.info().resting.length<normal.info().falling.length+normal.info().resting.length);
 const returning=T.createSeasonTouches(new THREE.Scene(),{tier:'low',random:()=>.417});returning.setPlan({});
 root.children[6].position.x=100;
 for(let t=0;t<=30;t++)returning.update(t,drop,calm,eye,opts);
 const originalTextures=new Set(returning.info().resting.map(p=>p.texture));assert.equal(originalTextures.size,6);
 const far=new THREE.Vector3(100,0,0);eye.position.x=100;eye.lookAt(far);eye.updateMatrixWorld();
 for(let t=31;t<=40;t++)returning.update(t,drop,calm,eye,{...opts,target:far});
 assert.ok(returning.info().falling.some(p=>p.texture===textures[6])||returning.info().resting.some(p=>p.texture===textures[6]));
 eye.position.x=0;eye.lookAt(0,0,0);eye.updateMatrixWorld();returning.update(41,summer,calm,eye,opts);
 for(const texture of originalTextures)assert.ok(returning.info().batches.some(b=>b.texture===texture&&b.object.visible),'returning to resting leaves restores their maps without new shedding');
 returning.dispose();
 for(const p of [normal,slow])p.dispose();for(const t of textures)t.dispose();
});
await test('shaft projection finite behind camera, horizon, half-space, screen edge, altitude and disabled',()=>{
 const eye=new THREE.PerspectiveCamera(60,16/9,.1,1000);eye.lookAt(0,0,-1);eye.updateMatrixWorld();
 const front=[0,0,-1],normal=lightShaftState(eye,{sunDir:front,sunAltDeg:3});assert.ok(normal.strength>0);
 for(const sunDir of [[0,0,1],[1,0,0],[0,0,0],[NaN,0,-1]]){
  const s=lightShaftState(eye,{sunDir,sunAltDeg:0});assert.equal(s.strength,0);assert.ok(s.uv.every(Number.isFinite));
 }
 for(const sunAltDeg of [-90,-2,0,3,12,90,NaN])for(const t of [0,.5,1,NaN]){
  const s=lightShaftState(eye,{sunDir:front,sunAltDeg,transmittance:t});assert.ok(Number.isFinite(s.strength));assert.ok(s.uv.every(Number.isFinite));
  if(t===0||!Number.isFinite(t)||sunAltDeg<=-2||sunAltDeg>=12)assert.equal(s.strength,0);
 }
 const cloudy=lightShaftState(eye,{sunDir:front,sunAltDeg:3,transmittance:.5});assert.ok(Math.abs(cloudy.strength/normal.strength-.5)<1e-8);
 assert.equal(lightShaftState(eye,{sunDir:front,sunAltDeg:3,enabled:false}).strength,0);
 for(const x of [0,.5,1,2,20])assert.ok(Number.isFinite(lightShaftState(eye,{sunDir:[x,0,-1],sunAltDeg:3}).strength));
});
await test('composer shafts use beauty depth even without clouds, fixed programs and bounded radial samples',()=>{
 for(const [tier,samples] of Object.entries({medium:16,high:24,max:32})){
  const r=new Renderer(),scene=new THREE.Scene(),eye=new THREE.PerspectiveCamera(60,1,.1,1000);eye.updateMatrixWorld();
  const p=createPost(r,scene,eye,{tier});assert.ok(p.target.depthTexture);
  p.setSun({sunDir:[0,0,-1],sunAltDeg:3});p.render();assert.equal(p.info().shafts.samples,samples);assert.ok(p.info().shafts.strength>0);
  const keys=p.shafts.materials.map(m=>[m.customProgramCacheKey(),m.version,m.fragmentShader]);
  for(const sunDir of [[0,0,1],[0,0,-1],[1,0,0]]){p.setSun({sunDir,sunAltDeg:0});p.render();}
  assert.deepEqual(p.shafts.materials.map(m=>[m.customProgramCacheKey(),m.version,m.fragmentShader]),keys);
  assert.ok(p.shafts.materials.every(m=>m.fragmentShader.includes('safeRGB')));p.dispose();
 }
});
await test('shaft draws share copied beauty depth, real directional cloud extinction and restore failed frames',async()=>{
 const {createCloudNoise,createCloudUniforms}=await import(file('static/twin/sky/clouds.js'));
 const noise=createCloudNoise({size:8,detail:4}),uniforms=createCloudUniforms(),clouds={noise,uniforms,active:false};
 const r=new Renderer(),scene=new THREE.Scene(),eye=new THREE.PerspectiveCamera(60,1,.1,1000);eye.updateMatrixWorld();
 const p=createPost(r,scene,eye,{clouds}),calls=[],draw=r.render;
 r.render=function(s,c){if(s.material?.name?.startsWith('season-shaft-'))calls.push([s.material.name,s.material.uniforms.depth.value,this.target]);draw.call(this,s,c);};
 const angle=3*Math.PI/180,sun={sunDir:[0,Math.sin(angle),-Math.cos(angle)],sunAltDeg:3};
 p.setSun(sun);p.render();const clear=p.info().shafts.strength;
 assert.deepEqual(calls.map(r=>r[0]),['season-shaft-radial','season-shaft-composite']);
 assert.ok(calls.every(r=>r[1]===p.shafts.depth.texture));assert.notEqual(calls[0][2],calls[1][2]);
 uniforms.cloudCoverage.value=1;uniforms.cloudType.value=3;uniforms.cloudFade.value=1;
 noise.base.image.data.fill(255);noise.detail.image.data.fill(255);p.render();
 assert.ok(p.info().shafts.strength<clear,'real cloud density attenuates sun direction');
 uniforms.cloudCoverage.value=0;p.render();assert.equal(p.info().shafts.strength,clear);
 const saved={target:r.getRenderTarget(),auto:r.autoClear,tone:r.toneMapping};
 r.render=function(s,c){if(s.material?.name==='season-shaft-radial')throw new Error('shaft failure');draw.call(this,s,c);};
 assert.throws(()=>p.render(),/shaft failure/);assert.equal(r.getRenderTarget(),saved.target);assert.equal(r.autoClear,saved.auto);assert.equal(r.toneMapping,saved.tone);
 let freed=0;for(const o of [p.shafts.depth,p.shafts.target,...p.shafts.materials])o.addEventListener('dispose',()=>freed++);
 p.dispose();p.dispose();assert.equal(freed,4);noise.dispose();
});
await test('household lawn material override disables fireflies on paving on every tier',async()=>{
 for(const tier of ['low','high']){
  location.search='?test=1';const plan=structuredClone(input.plan);plan.materials={...plan.materials,lawn:{id:'paving'}};
  const v=await mountTwin(new Element(),{plan,kit:{materials:{lawn:{color:'#00ff00'},paving:{asset:'concrete',color:'#888888'}}},tier,bake:false,site:{lat:40,lon:-74,source:'site'}});
  try{v.setClock('2026-07-15T04:00:00Z');v.setSeasonPreview('summer');v.setTime('night');v.render();assert.equal(v.seasonTouches.objects.fireflies.visible,false,'use the built lawn material, including house override');}
  finally{v.dispose();}
 }
});
await test('household mounted low/high, neutral editor, previews, interior/unlit exclusion and shared state',async()=>{
 for(const tier of ['low','high'])for(const editor of [false,true]){
  location.search='?test=1';const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}
  const v=await mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier,bake:false,site:{lat:40,lon:-74,source:'site'}});
  try{
   assert.ok(v.seasonTouches);assert.equal(!!v.post,tier!=='low');
   v.setClock('2026-07-15T04:00:00Z');v.setSeasonPreview('summer');v.setTime('night');v.render();
   assert.equal(v.seasonTouches.objects.fireflies.visible,!editor);
   if(v.post)assert.ok(v.post.info().passes.includes('LightShaftPass'));
   v.setUnlit(true);v.render();assert.ok(Object.values(v.seasonTouches.objects).every(o=>!o.visible));
   v.setUnlit(false);v.setView(v.levelKeys()[0]);v.render();assert.equal(v.seasonTouches.objects.fireflies.visible,false);
   if(v.post)assert.equal(v.post.info().shafts.strength,0);
  }finally{v.dispose();}
 }
});
finish();
"""

SOURCE_DRIVER = CLOUD_DRIVER.split("await test('lazy CPU texels")[0] + r"""
const {createSeasonTouches}=await import(file('static/twin/sky/season_touches.js'));
const {createPost}=await import(file('static/twin/post.js'));
await test('actual r187 particle and shaft sources: bounded budgets, no season keys, no shared lit changes',()=>{
 const scene=new THREE.Scene(),r=new Renderer(),p=createSeasonTouches(scene,{tier:'max'}),eye=new THREE.PerspectiveCamera(),cache=programs(r),lights=makeLights();
 r.toneMapping=THREE.ACESFilmicToneMapping;
 const chunks={...THREE.ShaderChunk},std=new THREE.MeshStandardMaterial(),o=new THREE.Mesh(new THREE.BoxGeometry(),std);
 const before=programSource(r,cache,scene,o,lights);
 for(const target of [null,new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType})]){
  r.setRenderTarget(target);const keys=new Map();
  for(const object of Object.values(p.objects)){
   const s=programSource(r,cache,scene,object,lights),budget=uniformBudget(s[2]);keys.set(object,s.key);
   assert.equal(budget.samplers.length,object.name==='season-fireflies'?0:1);assert.ok(budget.vectors<16);assert.ok(!s[2].includes('#include'));
   console.log(object.name,'fragment vectors',budget.vectors,'samplers',budget.samplers.length);
  }
  for(const autumn of [0,.5,1])for(const presence of [0,.5,1])for(const neutral of [true,false]){
   p.update(100,{autumn,presence,neutral,latitude:40,preview:'summer'},{temperatureC:22},eye,{sunAltDeg:-8});
   for(const object of Object.values(p.objects))assert.equal(programSource(r,cache,scene,object,lights).key,keys.get(object));
  }
  target?.dispose();
 }
 r.setRenderTarget(null);
 const after=programSource(r,cache,scene,o,lights);assert.equal(after.key,before.key);assert.equal(after[1],before[1]);assert.equal(after[2],before[2]);
 for(const tier of ['medium','high','max']){
  const post=createPost(r,scene,eye,{tier});
  for(const m of post.shafts.materials){
   const s=programSource(r,cache,scene,new THREE.Mesh(new THREE.PlaneGeometry(),m),lights),budget=uniformBudget(s[2]);
   assert.ok(budget.samplers.length<=3);assert.ok(budget.vectors<16);assert.ok(!s[2].includes('#include'));
   console.log(m.name,tier,'fragment vectors',budget.vectors,'samplers',budget.samplers.length);
   assert.ok(!s[2].includes('cloudShadowGrid'),'no shared lit shader in the post pass');
  }
  post.dispose();
 }
 assert.deepEqual(THREE.ShaderChunk,chunks);p.dispose();std.dispose();
});
finish();
"""

CAPTURE_DRIVER = REFLECTION_DRIVER.split('await test(')[0] + r"""
const {createSeasonTouches}=await import(file('static/twin/sky/season_touches.js'));
await test('real probe/mirror successes and failures exclude both touches and restore visibility',async()=>{
 const c=await setup('high'),p=createSeasonTouches(c.scene),camera=new THREE.PerspectiveCamera(60,16/9,.05,200);
 c.extra.push(p.group);for(const o of Object.values(p.objects))o.visible=true;
 let cube=0,mirror=0;c.renderer.inspect=()=>{cube++;assert.equal(p.group.visible,false);};
 c.round();assert.ok(cube>=6);assert.equal(p.group.visible,true);
 const pool=c.manager.info().probes.find(p=>p.id==='water:pool').centre;
 camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);camera.lookAt(new THREE.Vector3(...pool));camera.updateMatrixWorld();
 c.renderer.inspectMirror=()=>{mirror++;assert.equal(p.group.visible,false);};c.manager.mirror(camera);assert.ok(mirror>0);assert.equal(p.group.visible,true);
 c.renderer.fail=true;c.manager.request();c.round();assert.equal(p.group.visible,true);
 c.renderer.failMirror=true;c.manager.mirror(camera);assert.equal(p.group.visible,true);p.dispose();c.manager.dispose();
});
await test('viewer/editor mount warm hidden touch and post programs on picture destination before first reveal',async()=>{
 const original=globalThis.Renderer,compile=CaptureRenderer.prototype.compileAsync;globalThis.Renderer=CaptureRenderer;location.search='?test=1';
 const warm=[];CaptureRenderer.prototype.compileAsync=function(s,c){s.traverse(o=>{if(o.material?.name?.startsWith('season-'))warm.push([o.material.name,this.target]);});return Promise.resolve();};
 try{
  for(const editor of [false,true]){
   warm.length=0;const el=new Element();el.closest=selector=>editor&&selector==='.editor-shell'?el:null;
   const v=await mountTwin(el,{plan:fixture(),kit:kit(),tier:'high',bake:false});
   try{
    assert.deepEqual([...new Set(warm.map(r=>r[0]))].sort(),['season-fireflies','season-leaves','season-shaft-composite','season-shaft-radial']);
    assert.ok(warm.every(r=>r[1]===v.post.target));
    const pool=v.reflectionInfo().probes.find(p=>p.id==='water:pool').centre;
    v.camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);v.controls.target.set(...pool);v.camera.lookAt(v.controls.target);v.camera.updateMatrixWorld();
    let n=0;v.renderer3.inspectMirror=(s,c)=>{if(c===v.camera)return;n++;assert.equal(v.seasonTouches.group.visible,false);};v.render();assert.ok(n>0);
   }finally{v.dispose();}
  }
 }finally{globalThis.Renderer=original;if(compile)CaptureRenderer.prototype.compileAsync=compile;else delete CaptureRenderer.prototype.compileAsync;}
});
finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = flatten(assemble(fixture)[0])
    failed = False
    for driver in [DRIVER, SOURCE_DRIVER, CAPTURE_DRIVER]:
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'plan': plan}, timeout=600)
        print(output)
        failed |= bool(code)
    sys.exit(1 if failed else 0)
