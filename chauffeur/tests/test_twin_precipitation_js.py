"""Precipitation lifecycle and real household mount, executed in Node without GL."""
import json
from pathlib import Path
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_cloud_shadow_js import DRIVER as CLOUD_DRIVER
from test_twin_reflection_probes_js import DRIVER as REFLECTION_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {existsSync}=await import('node:fs');
assert.ok(existsSync(new URL(file('static/twin/sky/precipitation.js'))),'precipitation module exists');
const {createPrecipitation,precipitationCounts,precipitationVelocity,createSplashSampler,wrappedPosition}=await import(file('static/twin/sky/precipitation.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const weather=(precip='rain',rate=1)=>({precip,rate,windMps:0,windToDeg:90});
await test('floor, room, building and steep camera views hide every precipitation draw',()=>{
 const p=createPrecipitation(new THREE.Scene(),{tier:'low'}),eye=new THREE.PerspectiveCamera();
 const target=new THREE.Vector3();eye.position.set(0,5,20);eye.lookAt(target);eye.updateMatrixWorld();
 for(const level of ['house','floor','room','building'])for(const kind of ['rain','snow','mix','hail']){
  p.update(1,weather(kind),eye,{target,level});
  assert.equal(p.objects[kind==='mix'?'rain':kind].visible,level==='house');
  if(level!=='house')assert.ok(Object.values(p.objects).every(o=>!o.visible&&o.geometry.instanceCount===0));
 }
 for(const degrees of [54.9,55,55.1,89.9]){
  eye.position.set(0,30*Math.sin(degrees*Math.PI/180),30*Math.cos(degrees*Math.PI/180));eye.lookAt(target);eye.updateMatrixWorld();
  p.update(2,weather(),eye,{target,level:'house'});assert.equal(p.objects.rain.visible,degrees<=55);
 }
 p.dispose();
});
await test('verbatim tier budgets, intensity, mixed weather, invalid input and neutral',()=>{
 for(const [tier,n] of Object.entries({low:3000,medium:4000,high:8000,max:12000})){
  assert.deepEqual(precipitationCounts(tier,weather()),{rain:n,snow:0,hail:0});
  assert.equal(precipitationCounts(tier,weather('snow')).snow,n/2);
  assert.equal(precipitationCounts(tier,weather('hail')).hail,n*.3);
  assert.equal(precipitationCounts(tier,weather('rain',.4)).rain,Math.floor(n*.4));
  assert.deepEqual(precipitationCounts(tier,weather('mix')),{rain:n/2,snow:n/4,hail:0});
  for(const w of [weather('rain',0),weather('rain',NaN),weather('none'),{...weather(),neutral:true}])
   assert.deepEqual(precipitationCounts(tier,w),{rain:0,snow:0,hail:0});
 }
});
await test('physical wind toward compass bearing and only precipitation slows for reduced motion',()=>{
 const w={...weather('snow'),windMps:10,windToDeg:90};
 const v=precipitationVelocity('snow',w,180),r=precipitationVelocity('snow',w,180,true);
 assert.ok(v[0]>0&&Math.abs(v[2])<1e-8);assert.equal(v[1],-.9);
 for(let i=0;i<3;i++)assert.ok(Math.abs(r[i]-v[i]*.35)<1e-9);
 assert.ok(Math.abs(precipitationVelocity('rain',{...w,windToDeg:0},90)[0]-10)<1e-8);
 assert.deepEqual(precipitationVelocity('rain',{windMps:NaN,windToDeg:NaN},NaN),[0,-14,0]);
});
await test('rain projected width has a 1.25 pixel floor, viewport tracks the target and rate controls opacity',()=>{
 const scene=new THREE.Scene(),p=createPrecipitation(scene,{tier:'low'}),camera=new THREE.PerspectiveCamera(60,16/9,.05,500);
 const material=p.objects.rain.material,body=material.vertexShader.match(/float precipitationWidth\(float pixels,float kind\) \{([\s\S]*?)\n\}/)[1];
 const width=new Function('max',`return (pixels,kind)=>{${body}}`)(Math.max);
 for(const [w,h] of [[1600,900],[1920,1080],[960,540],[320,240]]){
  p.objects.rain.onBeforeRender({getDrawingBufferSize:out=>out.set(w,h)});
  assert.deepEqual(p.uniforms.precipViewport.value.toArray(),[w,h]);
  for(const depth of [.1,1,5,20,40,64,100,500])for(const angle of [0,.4,1.57]){
   const side=new THREE.Vector4(Math.cos(angle)*.018,Math.sin(angle)*.018,0,0).applyMatrix4(camera.projectionMatrix);
   const physical=Math.hypot(side.x*w*.5,side.y*h*.5)/depth;
   assert.ok(width(physical,0)>=1.25);assert.equal(width(physical,1),physical);assert.equal(width(physical,2),physical);
  }
 }
 assert.ok(material.vertexShader.includes('side*position.x*width)*2.0/viewport*gl_Position.w'),'width expands in clip space independently of length');
 assert.ok(material.fragmentShader.includes('mix(.35,.85,precipRate)'),'alpha scales with rain rate');
 p.update(0,{precip:'rain',rate:.45},camera);assert.equal(p.uniforms.precipRate.value,.45);
 p.update(1,{precip:'rain',rate:1},camera);assert.equal(p.uniforms.precipRate.value,1);
 assert.deepEqual(p.uniforms.precipColour.value.toArray(),[.6,.7,.8]);
 assert.ok(material.fragmentShader.includes('precipColour*(precipKind<.5?1.2:1.0)'),'only rain lifts the sky tint');p.dispose();
});
await test('rain length floors fade below 4 px to a dot, with independent width and no drops inside 3 metres',()=>{
 const p=createPrecipitation(new THREE.Scene()),m=p.objects.rain.material;
 const body=m.vertexShader.match(/float precipitationLength\(float pixels,float kind,float rate\) \{([\s\S]*?)\n\}/)[1];
 const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/(b-a)));return t*t*(3-2*t);};
 const length=new Function('max','mix','clamp','smoothstep',`return (pixels,kind,rate)=>{${body}}`)(Math.max,(a,b,t)=>a+(b-a)*t,(v,a,b)=>Math.max(a,Math.min(b,v)),smoothstep);
 assert.equal(length(0,0,1),1.25,'camera-axis streak is a dot');
 for(const pixels of [.01,.1,1,2,3])assert.ok(length(pixels,0,1)<10,'sub-4px streak floor fades out');
 for(const rate of [.45,1])for(const viewport of [[1920,1080],[960,540],[320,240]])for(const depth of [2.5,3,20,60,100,500])for(const velocity of [[0,-14,0],[5,-14,4],[0,0,0],[0,0,-14]]){
  const camera=new THREE.PerspectiveCamera(38,viewport[0]/viewport[1],.1,1000),eye=new THREE.Vector4(.1,.2,-depth,1);
  const fall=new THREE.Vector3(...velocity);if(fall.length()>1e-5)fall.normalize();else fall.set(0,-1,0);
  const project=v=>v.applyMatrix4(camera.projectionMatrix),clip=project(eye.clone());
  const head=project(eye.clone().add(new THREE.Vector4(...fall.toArray(),0).multiplyScalar(.35)));
  const tail=project(eye.clone().sub(new THREE.Vector4(...fall.toArray(),0).multiplyScalar(.35)));
  const delta=new THREE.Vector2((head.x/Math.max(Math.abs(head.w),.0001)-tail.x/Math.max(Math.abs(tail.w),.0001))*viewport[0]*.5,
    (head.y/Math.max(Math.abs(head.w),.0001)-tail.y/Math.max(Math.abs(tail.w),.0001))*viewport[1]*.5);
  const physical=delta.length(),direction=physical>1e-5?delta.clone().divideScalar(Math.max(physical,1e-5)):new THREE.Vector2(0,-1);
  const pixels=length(physical,0,rate);if(physical>=4)assert.ok(pixels>=(rate===1?10:6));else assert.ok(pixels<(rate===1?10:6));
  for(const kind of [1,2])assert.equal(length(physical,kind,rate),physical,'snow/hail keep physical length');
  const side=new THREE.Vector2(-direction.y,direction.x),corners=[];
  for(const [x,y] of [[-.5,-.5],[.5,-.5],[.5,.5],[-.5,.5]]){
   const offset=direction.clone().multiplyScalar(y*pixels).addScaledVector(side,x*1.25);
   const c=clip.clone();c.x+=offset.x*2/viewport[0]*clip.w;c.y+=offset.y*2/viewport[1]*clip.w;
   corners.push(new THREE.Vector2(c.x/c.w*viewport[0]*.5,c.y/c.w*viewport[1]*.5));assert.ok(c.toArray().every(Number.isFinite));
  }
  assert.ok(Math.abs(corners[0].distanceTo(corners[1])-1.25)<1e-8,'length floor never stretches width');
  assert.ok(Math.abs(corners[1].distanceTo(corners[2])-pixels)<1e-8);
  assert.ok(Math.abs(direction.dot(side))<1e-9);
 }
 assert.ok(m.vertexShader.includes('direction*position.y*streakLength'));
 assert.ok(m.vertexShader.includes('eye.xy+=side*position.x*size.x+direction*position.y*size.y;'),'snow/hail preserve physical billboards, including top view');
 assert.ok(m.vertexShader.includes('if(distance(world,cameraPosition)<3.0){gl_Position=vec4(2.0,2.0,2.0,1.0);return;}'));
 assert.ok(m.fragmentShader.includes('if(distance(particleWorld,cameraPosition)<3.0)discard;'));
 assert.ok(m.fragmentShader.includes('smoothstep(halfExtent*.8,halfExtent,edge)'),'outer fifth of focus box fades');
 assert.ok(!m.fragmentShader.includes('smoothstep(40.0,64.0'));p.dispose();
});
await test('actual fade function scales with box edges and excludes near-camera drops',()=>{
 const p=createPrecipitation(new THREE.Scene());
 const body=p.objects.rain.material.fragmentShader.match(/float precipitationFade\(\)\{([\s\S]*?)\n\}/)[1].replace(/\bfloat /g,'const ');
 const distance=(a,b)=>Math.hypot(...a.map((v,i)=>v-b[i]));
 const smoothstep=(a,b,x)=>{const t=Math.max(0,Math.min(1,(x-a)/Math.max(b-a,.0001)));return t*t*(3-2*t);};
 const fade=new Function('particleWorld','cameraPosition','precipRadius','precipFog','precipCentre','precipAnchor','precipBox','distance','smoothstep','max','exp',body);
 const world=(x,y,z)=>Object.assign([x,y,z],{xz:[x,z]});
 for(const h of [18,30,64]){
  const evaluate=(x,d=10)=>fade(world(x,5,0),[x,5,d],10000,0,[0,0],world(0,0,0),{x:2*h},distance,smoothstep,Math.max,Math.exp);
  assert.equal(evaluate(.8*h),1);assert.ok(Math.abs(evaluate(.9*h)-.5)<1e-9);
  assert.equal(evaluate(h),0);assert.equal(evaluate(2*h),0);
  for(const d of [0,1,2.49,2.5,2.99,3])assert.equal(evaluate(0,d),0);
  assert.equal(evaluate(0,3.5),1);assert.equal(evaluate(0,100),1,'camera distance no longer removes rain at the house');
 }
 const fogFade=fade(world(0,5,0),[0,5,150],10000,3.912/300,[0,0],world(0,0,0),{x:128},distance,smoothstep,Math.max,Math.exp);
 assert.ok(Math.abs(fogFade-Math.exp(-3.912/2))<1e-10,'particle veil uses camera distance');
 p.dispose();
});
await test('focus box wraps in shader coordinates without moving every seed',()=>{
 const p=wrappedPosition([.1,.2,.3],[4,-5,6],[10,20,30]);
 const moved=wrappedPosition([.1,.2,.3],[4,-5,6],[11,21,31]);
 assert.deepEqual(moved,p,'a small camera move keeps the same world particles');
 const far=wrappedPosition([.1,.2,.3],[4,-5,6],[1000,2000,3000]);
 for(let i=0;i<3;i++)assert.ok(Math.abs(far[i]-[1000,2000,3000][i])<=[64,48,64][i]);
 const scene=new THREE.Scene(),pfx=createPrecipitation(scene,{tier:'low'}),camera=new THREE.PerspectiveCamera();
 const seeds=pfx.objects.rain.geometry.attributes.precipSeed,version=seeds.version,copy=seeds.array.slice();
 const target=new THREE.Vector3(10,0,20);
 pfx.update(0,weather(),camera,{target});camera.position.set(100,80,-50);pfx.update(1,weather(),camera,{target});
 assert.equal(pfx.uniforms.precipAnchor.value.x,41.5);assert.equal(pfx.uniforms.precipAnchor.value.z,-4.5);
 assert.deepEqual(pfx.uniforms.precipBox.value.toArray(),[128,88,128]);
 assert.equal(pfx.uniforms.precipAnchor.value.y,44);assert.equal(seeds.version,version);assert.deepEqual(seeds.array,copy);
 for(const eye of [[10,1,20],[10,10,60],[10,200,420]]){
  camera.position.fromArray(eye);pfx.update(2,weather(),camera,{target});
  const box=pfx.uniforms.precipBox.value,anchor=pfx.uniforms.precipAnchor.value;
  assert.equal(box.x,2*Math.max(18,Math.min(64,.75*camera.position.distanceTo(target))));
  assert.equal(box.z,box.x);assert.equal(anchor.y-box.y/2,0);
  assert.equal(anchor.y+box.y/2,Math.max(25,camera.position.y+8));
  const world=wrappedPosition([.1,.2,.3],[4,-5,6],anchor.toArray(),box.toArray());
  world.forEach((v,i)=>assert.ok(Math.abs(v-anchor.getComponent(i))<=box.getComponent(i)/2));
 }
 assert.equal(seeds.version,version);assert.deepEqual(seeds.array,copy);
 pfx.setPlan({site:{terraces:[{polygon:[[0,0],[100,0],[100,100],[0,100]],height:10,blend:0}]}});
 camera.position.set(10,5,-10);target.set(10,0,-10);pfx.update(3,weather(),camera,{target});
 assert.ok(Math.abs(pfx.uniforms.precipAnchor.value.y-pfx.uniforms.precipBox.value.y/2-3.048)<1e-9,'bottom follows ground under target');
 assert.ok(pfx.objects.rain.material.vertexShader.includes('mod('));pfx.dispose();
});
await test('hard upward splash sampling uses layered ground, path, deck and roof heights; excludes beds, grass, water and interiors',()=>{
 const plan={site:{terraces:[{polygon:[[0,0],[20,0],[20,20],[0,20]],height:3,blend:0,material:'lawn'}],
  hardscape:[{polygon:[[0,0],[10,0],[10,10],[0,10]],elevation:1},{kind:'path',points:[[25,0],[25,20]],width:4}],
  beds:[{polygon:[[1,1],[3,1],[3,3],[1,3]]}],pool:{polygon:[[4,4],[6,4],[6,6],[4,6]],features:[{kind:'spa',polygon:[[7,7],[9,7],[9,9],[7,9]]}]}},
  buildings:[{id:'b',position:[40,0],rotation:90,base:2,levels:[{id:'l',elevation:0,outline:[[0,0],[10,0],[10,10],[0,10]]}],porches:[{polygon:[[12,0],[16,0],[16,4],[12,4]],floor:5}]}]};
 const roofs=new Map([['b',{sections:[{kind:'flat',rect:[0,0,10,10],plate:12}]}]]),sample=createSplashSampler(plan,roofs);
 assert.ok(Math.abs(sample(1.5*.3048,-5*.3048).position[1]-4.3*.3048-.006)<1e-8);
 for(const [x,y] of [[2,2],[5,5],[8,8],[15,15],[100,100]])assert.equal(sample(x*.3048,-y*.3048),null);
 assert.ok(sample(25*.3048,-5*.3048));
 assert.ok(Math.abs(sample(38*.3048,-14*.3048).position[1]-7*.3048-.006)<1e-8,'rotated deck');
 const roof=sample(35*.3048,-5*.3048);assert.equal(roof.kind,'roof');assert.ok(Math.abs(roof.position[1]-14*.3048-.006)<1e-8);
 const interior=createSplashSampler(plan,new Map());assert.equal(interior(35*.3048,-5*.3048),null);
});
await test('fixed material identities/keys, one draw per kind plus splashes, bounded spawning and disposal',()=>{
 let randomCalls=0;
 const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),p=createPrecipitation(scene,{tier:'high',random:()=>{randomCalls++;return .5;}});
 p.setStage({centre:[0,0],radius:100});
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}},new Map());randomCalls=0;
 const entries=Object.values(p.objects),materials=entries.map(o=>o.material),keys=materials.map(m=>m.customProgramCacheKey()),versions=materials.map(m=>m.version);
 let time=0;
 for(const kind of ['none','rain','snow','mix','hail','rain']){
  p.update(time++,weather(kind),camera);p.update(time++,weather(kind),camera);
  assert.equal(entries.filter(o=>o.visible&&o.geometry.instanceCount>0).length,{none:0,rain:2,snow:1,mix:3,hail:1}[kind],kind+' draw submissions');
 }
 assert.ok(randomCalls/2<=6*12,'bounded catch-up after stalls');
 assert.ok(p.objects.splash.geometry.instanceCount<=64);
 assert.deepEqual(entries.map(o=>o.material),materials);assert.deepEqual(materials.map(m=>m.customProgramCacheKey()),keys);assert.deepEqual(materials.map(m=>m.version),versions);
 assert.equal(entries.length,4);
 for(const o of entries){assert.equal(o.castShadow,false);assert.equal(o.receiveShadow,false);assert.equal(o.layers.isEnabled(31),false);assert.equal(o.material.lights,false);assert.equal(o.material.depthWrite,false);assert.equal(o.material.forceSinglePass,true,'flat double-sided particles submit once');assert.deepEqual(o.raycast(),undefined);}
 p.update(3,{...weather(),neutral:true},camera);assert.ok(entries.every(o=>!o.visible));
 p.update(4,weather(),camera,{unlit:true});assert.ok(entries.every(o=>!o.visible));
 let released=0;for(const o of entries){o.geometry.addEventListener('dispose',()=>released++);o.material.addEventListener('dispose',()=>released++);}
 p.dispose();p.dispose();assert.equal(released,8);assert.equal(scene.children.length,0);
});
await test('rain splashes have bounded real-time lifetime/rate and do not multiply on reduced-motion or stale frames',()=>{
 let rng=0;const random=()=>{rng++;return .5;},scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera();
 const p=createPrecipitation(scene,{tier:'low',random});
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});rng=0;
 p.update(0,weather(),camera);
 for(let t=1;t<=100;t++)p.update(t/100,weather(),camera,{reduced:true});
 assert.ok(rng/2>=23&&rng/2<=24,'24 candidate samples per second on low, motion does not slow the weather rate');
 const born=p.objects.splash.geometry.attributes.splashBorn.array;
 assert.ok(born.some(t=>t>=.58&&t<=1));assert.equal(p.objects.splash.visible,true);
 const count=rng;p.update(1000,weather(),camera);assert.ok((rng-count)/2<=12,'bounded catch-up after long sleep');
 p.update(1001,weather('snow'),camera);assert.equal(p.objects.splash.visible,false);assert.ok(born.every(t=>t<0));
 p.dispose();
});
await test('steep roof blocks the deck beneath it, and sampler refresh follows edits',()=>{
 const plan={buildings:[{id:'b',levels:[{id:'l',elevation:0}],porches:[{polygon:[[0,0],[20,0],[20,20],[0,20]],floor:2}]}]};
 const roofs=new Map([['b',{sections:[{kind:'shed',rect:[0,0,20,20],plate:20,pitch:24,low_side:'x0'}]}]]);
 assert.equal(createSplashSampler(plan,roofs)(5*.3048,-5*.3048),null,'no sprite under a steep roof');
 const p=createPrecipitation(new THREE.Scene(),{tier:'low',random:()=>.5}),camera=new THREE.PerspectiveCamera();
 p.setPlan({site:{hardscape:[{polygon:[[-200,-200],[200,-200],[200,200],[-200,200]]}]}});p.update(0,weather(),camera);p.update(1,weather(),camera);
 assert.equal(p.objects.splash.visible,true);p.setPlan({});p.update(2,weather(),camera);assert.equal(p.objects.splash.visible,false);p.dispose();
});
await test('paver paths splash on the stones at their actual height, never the lawn gaps',async()=>{
 const {yardPaverLayout}=await import(file('static/twin/paver_path.js'));
 const path={kind:'path',id:'stepping',points:[[0,0],[0,20]],width:4,pavers:{layout:'stepping',length_in:24,width_in:24,gap_in:12,lay:'level',joint:'lawn'}};
 const layout=yardPaverLayout(path),sample=createSplashSampler({site:{hardscape:[path]}});
 assert.ok(layout.pavers.length>1);const centre=layout.pavers[0].centre,hit=sample(centre[0]*.3048,-centre[1]*.3048);
 assert.ok(hit);assert.ok(Math.abs(hit.position[1]-(1/12)*.3048-.006)<1e-8,'paver tops stand one inch over grade');
 assert.equal(sample(1.8*.3048,-centre[1]*.3048),null,'lawn beside the stepping stones is not hardscape');
});
await test('same precipitation draws over cloud composite and before bloom; AO excludes it',async()=>{
 const {createPost}=await import(file('static/twin/post.js'));
 const {createCloudPass}=await import(file('static/twin/sky/cloud_pass.js'));
 const {createCloudNoise}=await import(file('static/twin/sky/clouds.js'));
 const r=new Renderer(),scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(),noise=createCloudNoise({size:8,detail:4});
 const cloud=createCloudPass(r,{tier:'high',noise}),p=createPrecipitation(scene,{tier:'low'});p.update(0,weather('mix'),camera);
 cloud.update({coverage:1,type:'nimbostratus'});cloud.frame(1);
 const post=createPost(r,scene,camera,{clouds:cloud}),calls=[],draw=r.render;
 r.render=function(s,c){
  if(s===scene)calls.push({scene:true,override:!!s.overrideMaterial,visible:Object.values(p.objects).filter(o=>o.visible&&o.layers.test(c.layers)).map(o=>o.name)});
  else calls.push({name:s.material?.name,fragment:s.material?.fragmentShader});
  return draw.call(this,s,c);
 };
 post.render();const composite=calls.findIndex(c=>c.name==='twin-cloud-composite');
 const particles=calls.findIndex(c=>c.visible?.includes('weather-rain'));
 assert.ok(particles>composite&&composite>=0);
 assert.ok(calls.slice(0,particles).filter(c=>c.scene).every(c=>!c.visible.length),'beauty opaque/AO omit precipitation');
 assert.ok(calls.slice(particles+1).some(c=>c.fragment?.includes('luminosityThreshold')),'bloom follows precipitation');
 cloud.update({coverage:0,type:'none'});calls.length=0;post.render();assert.equal(calls.filter(c=>c.visible?.includes('weather-rain')).length,1,'clear composer draws each kind once');
 calls.length=0;r.render(scene,camera);assert.equal(calls[0].visible.length,2,'plain canvas draws the same rain and snow');
 post.dispose();cloud.dispose();noise.dispose();p.dispose();
});
await test('real household mount: previews, editor neutral/Live, Unlit, captures, hide/lock and cleanup',async()=>{
 let v,e;try{
  const mount=async(editor=false)=>{const el=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(el);}return mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});};
  v=await mount();e=await mount(true);assert.ok(v.precipitation);assert.ok(e.precipitation);
  const states={'weather.home':{state:'pouring',attributes:{}}};
  for(const x of [v,e])x.live={peek:()=>states,stale:()=>false,draw(){},stop(){},closeRoom(){}};
  v.setTime('day');e.setTime('day');assert.equal(v.precipitation.objects.rain.geometry.instanceCount,3000);assert.equal(e.precipitation.objects.rain.visible,false);
  const mats=Object.values(v.precipitation.objects).map(o=>o.material.uuid);
  const building=v.plan.buildings.find(b=>b.rooms?.length),room=building.rooms.find(r=>r.state!=='ghost');
  for(const level of [{building:building.id,floor:room.level},{building:building.id,room:room.id}]){
   v.levels.go(level,{immediate:true});v.render();
   assert.ok(Object.values(v.precipitation.objects).every(o=>!o.visible&&o.geometry.instanceCount===0),'real floor/room levels suppress precipitation');
  }
  v.levels.go({level:'house'},{immediate:true});v.render();assert.equal(v.precipitation.objects.rain.visible,true);
  e.setLiveWeather(true);e.setView(e.levelKeys()[0]);e.render();assert.ok(Object.values(e.precipitation.objects).every(o=>!o.visible&&o.geometry.instanceCount===0));e.setView('ext');
  for(const name of ['clear','rain','pouring','snow','fog','thunderstorm']){v.setWeatherPreview(name);assert.equal(v.precipitation.objects.snow.visible,name==='snow');}
  e.setLiveWeather(true);assert.equal(e.precipitation.objects.rain.visible,true);
  v.setUnlit(true);assert.ok(Object.values(v.precipitation.objects).every(o=>!o.visible));v.setUnlit(false);v.setTime('now');
  assert.equal(v.precipitation.objects.rain.visible,true);assert.deepEqual(Object.values(v.precipitation.objects).map(o=>o.material.uuid),mats);
  const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));const visibility=createPieceVisibility();visibility.set(new Set(),new Set(['effect','planting','roof','hardscape']));visibility.apply(v.scene);
  assert.equal(v.precipitation.objects.rain.visible,true);visibility.restore();
  const sample=createSplashSampler(v.plan,v.roofSurfaces);let hits=0;
  for(let x=-30;x<180;x+=4)for(let y=-30;y<180;y+=4){const hit=sample(x*.3048,-y*.3048);if(hit){hits++;assert.ok(hit.position.every(Number.isFinite));assert.ok(hit.normal[1]>.55);}}
  assert.ok(hits>0,'actual household has splash receivers');
 }finally{v?.dispose();e?.dispose();}
});
await test('1920x1080 household low-tier frustum census uses identical seeds before and after',async()=>{
 let v,p;try{
  const el=new Element();el.clientWidth=1920;el.clientHeight=1080;
  v=await mountTwin(el,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'low',bake:false});
  v.camera.aspect=1920/1080;v.camera.updateProjectionMatrix();v.levels.go({level:'house'},{immediate:true});
  let rng=0x12345678;p=createPrecipitation(new THREE.Scene(),{tier:'low',random:()=>{rng=(Math.imul(rng,1664525)+1013904223)>>>0;return rng/4294967296;}});
  p.setPlan(v.plan,v.roofSurfaces);
  const seed=p.objects.rain.geometry.attributes.precipSeed,version=seed.version,copy=seed.array.slice();
  for(const framing of ['house','weather-harness']){
   if(framing==='weather-harness'){
    // Exactly horizon_look() in test_twin_weather_live.py, without a browser.
    const c=v.controls.target.clone(),d=v.camera.position.clone().sub(c);d.y=Math.max(3,d.length()*.08);
    v.setCameraState({position:c.clone().add(d).toArray(),target:c.toArray()});
   }
   v.camera.updateMatrixWorld(true);
   const eye=v.camera.position,target=v.controls.target,houseDistance=eye.distanceTo(target);
   const frustum=new THREE.Frustum().setFromProjectionMatrix(new THREE.Matrix4().multiplyMatrices(v.camera.projectionMatrix,v.camera.matrixWorldInverse));
   for(const rate of [.45,1]){
    p.update(0,weather('rain',rate),v.camera,{target});
    const count=p.objects.rain.geometry.instanceCount,box=p.uniforms.precipBox.value.toArray(),anchor=p.uniforms.precipAnchor.value.toArray();
    const results={};
    for(const before of [true,false]){
     let inside=0,nearer=0,nonzeroFade=0;
     for(let i=0;i<count;i++){
      const s=Array.from(seed.array.subarray(i*3,i*3+3));
      const world=new THREE.Vector3(...wrappedPosition(s,[0,0,0],before?eye.toArray():anchor,before?[128,96,128]:box));
      if(!frustum.containsPoint(world))continue;inside++;
      const distance=world.distanceTo(eye);if(distance>=houseDistance)continue;nearer++;
      const radial=Math.hypot(world.x-anchor[0],world.z-anchor[2]);
      if(distance>(before?.8:2.5)&&(before?distance<64:radial<box[0]/2))nonzeroFade++;
     }
     results[before?'before':'after']={inside,nearer,nonzeroFade};
    }
    assert.ok(results.after.nearer>results.before.nearer,'density rises in front of the house');
    assert.ok(results.after.nonzeroFade>results.before.nonzeroFade,'extra instances survive distance and near fades');
    console.log('FRUSTUM_CENSUS',JSON.stringify({framing,rate,count,eye:eye.toArray(),target:target.toArray(),houseDistance,box,anchor,...results}));
   }
  }
  assert.equal(seed.version,version);assert.deepEqual(seed.array,copy);
 }finally{p?.dispose();v?.dispose();}
});
finish();
"""

SOURCE_DRIVER = CLOUD_DRIVER.split("await test('lazy CPU texels")[0] + r"""
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
await test('actual r187 source assembly and keys: all kinds warmed at mount, no weather programs/samplers or shared lit changes',()=>{
 const scene=new THREE.Scene(),r=new Renderer(),p=createPrecipitation(scene,{tier:'max'}),eye=new THREE.PerspectiveCamera(),cache=programs(r),lights=makeLights();
 r.toneMapping=THREE.ACESFilmicToneMapping;
 const chunks={...THREE.ShaderChunk},std=new THREE.MeshStandardMaterial(),stdKey=std.customProgramCacheKey();
 for(const target of [null,new THREE.WebGLRenderTarget(8,8,{type:THREE.HalfFloatType})]){
  r.setRenderTarget(target);const keys=new Map();
  for(const o of Object.values(p.objects)){
   const s=programSource(r,cache,scene,o,lights);keys.set(o,s.key);const budget=uniformBudget(s[2]);
   assert.equal(budget.samplers.length,0);assert.ok(budget.vectors<20);assert.ok(s[1].includes('projectionMatrix'));assert.ok(s[2].includes('precipSafe'));
   assert.ok(!s[2].includes('#include'));console.log(o.name,'fragment vectors',budget.vectors);
  }
  assert.equal(new Set(keys.values()).size,2,'falling kinds share a program, splashes have their own');
  for(const precip of ['none','rain','snow','mix','hail'])for(const neutral of [true,false]){
   p.update(100,{precip,neutral,rate:1,windMps:20,windToDeg:270,fog:.7},eye,{colour:[.015,.02,.03]});
   for(const o of Object.values(p.objects))assert.equal(programSource(r,cache,scene,o,lights).key,keys.get(o));
  }
  for(const position of [[0,0,0],[5,40,10],[200,80,-100]]){
   eye.position.fromArray(position);p.update(101,{precip:'rain',rate:.45},eye,{target:new THREE.Vector3(10,0,-10)});
   for(const o of Object.values(p.objects))assert.equal(programSource(r,cache,scene,o,lights).key,keys.get(o),'focus/box changes are uniforms only');
  }
  target?.dispose();
 }
 assert.deepEqual(THREE.ShaderChunk,chunks);assert.equal(std.customProgramCacheKey(),stdKey);std.dispose();p.dispose();
});
finish();
"""

CAPTURE_DRIVER = REFLECTION_DRIVER.split("await test(")[0] + r"""
const {createPrecipitation}=await import(file('static/twin/sky/precipitation.js'));
await test('real probe/mirror passes hide precipitation and restore it after successful and failed captures',async()=>{
 const c=await setup('high'),p=createPrecipitation(c.scene,{tier:'high'}),camera=new THREE.PerspectiveCamera(60,16/9,.05,200);
 c.extra.push(p.group);p.update(0,{precip:'rain',rate:1},camera);
 let cube=0,mirror=0;
 c.renderer.inspect=()=>{cube++;assert.equal(p.group.visible,false);};
 c.round();assert.ok(cube>=6);assert.equal(p.group.visible,true);
 const pool=c.manager.info().probes.find(p=>p.id==='water:pool').centre;
 camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);camera.lookAt(new THREE.Vector3(...pool));camera.updateMatrixWorld();
 c.renderer.inspectMirror=()=>{mirror++;assert.equal(p.group.visible,false);};
 c.manager.mirror(camera);assert.ok(mirror>0);assert.equal(p.group.visible,true);
 c.renderer.fail=true;c.manager.request();c.round();assert.equal(p.group.visible,true);
 c.renderer.failMirror=true;c.manager.mirror(camera);assert.equal(p.group.visible,true);
 p.dispose();c.manager.dispose();
});
await test('real high-tier mount warms hidden precipitation materials for the composer, and excludes them from mirror',async()=>{
 location.search='?test=1';const original=globalThis.Renderer,loop=CaptureRenderer.prototype.setAnimationLoop;
 globalThis.Renderer=CaptureRenderer;CaptureRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 const warm=[],compile=CaptureRenderer.prototype.compileAsync;
 CaptureRenderer.prototype.compileAsync=function(s,c){s.traverse(o=>{if(o.name?.startsWith('weather-')&&o.material)warm.push([o.name,this.target,o.visible]);});return Promise.resolve();};
 let v;try{
  v=await mountTwin(new Element(),{plan:fixture(),kit:kit(),tier:'high',bake:false});await Promise.resolve();
  assert.equal(new Set(warm.map(r=>r[0])).size,4);assert.ok(warm.every(r=>r[1]===v.post.target),'warm against the picture destination');
  v.setWeatherPreview('pouring');await new Promise(resolve=>setTimeout(resolve,0));v.render();
  assert.equal(v.precipitation.objects.rain.visible,true,'rain appears after asynchronous warmup releases the frame');
  const pool=v.reflectionInfo().probes.find(p=>p.id==='water:pool').centre;
  v.camera.position.set(pool[0]-9,pool[1]+1.7,pool[2]+2);v.controls.target.set(...pool);v.camera.lookAt(v.controls.target);v.camera.updateMatrixWorld();
  let draws=0;v.renderer3.inspectMirror=(s,c)=>{if(c===v.camera)return;draws++;assert.equal(v.precipitation.group.visible,false);};v.render();
  assert.ok(draws>0);assert.equal(v.precipitation.group.visible,true);assert.equal(v.precipitation.objects.rain.visible,true);
 }finally{v?.dispose();globalThis.Renderer=original;CaptureRenderer.prototype.setAnimationLoop=loop;if(compile)CaptureRenderer.prototype.compileAsync=compile;else delete CaptureRenderer.prototype.compileAsync;}
});
await test('neutral editor warms every precipitation program before a person selects Live weather',async()=>{
 location.search='?test=1';const original=globalThis.Renderer,compile=CaptureRenderer.prototype.compileAsync;
 globalThis.Renderer=CaptureRenderer;const warm=[];
 CaptureRenderer.prototype.compileAsync=function(s,c){s.traverse(o=>{if(o.name?.startsWith('weather-')&&o.material)warm.push(o.name);});return Promise.resolve();};
 let v;try{
  const el=new Element();el.closest=selector=>selector==='.editor-shell'?el:null;
  v=await mountTwin(el,{plan:fixture(),kit:kit(),tier:'high',bake:false});
  assert.equal(new Set(warm).size,4,'editor warms all hidden precipitation materials');
  assert.ok(Object.values(v.precipitation.objects).every(o=>!o.visible));
 }finally{v?.dispose();globalThis.Renderer=original;if(compile)CaptureRenderer.prototype.compileAsync=compile;else delete CaptureRenderer.prototype.compileAsync;}
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
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'plan': plan}, timeout=180)
        print(output)
        failed |= bool(code)
    sys.exit(1 if failed else 0)
