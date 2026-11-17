"""Execute water integration, real standard shader anchors and simulation contracts."""
import subprocess
import sys
import json
import shutil
import uuid
from pathlib import Path

from test_twin_untouched_house_js import COMMON

ROOT = Path(__file__).resolve().parents[1]
DRIVER = COMMON + r"""
const Y=await import(file('static/twin/twin_yard.js'));
const W=await import(file('static/twin/effects/water_ripples.js'));
const S=await import(file('static/twin/effects/water_surface.js'));
const U=await import(file('static/twin/effects/underwater.js'));
const SIM=await import(file('static/twin/effects/water_sim.js'));
const {buildEffects}=await import(file('static/twin/effects/index.js'));
const {createUnlit}=await import(file('static/twin/unlit.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const effect={id:'fountain',type:'fountain',shape:'point',ref:'absolute',at:[16,10,0],strength:1};
const plan=(raised=true,sourced=true)=>({units:'ft',buildings:[],materials:{},site:{lot:square(-8,-8,64),
 hardscape:[{id:'outside',polygon:square(38,4,10),material:'paving'}],
 pool:{id:'pool',polygon:square(0,0,32,24),depth:5,coping:1,elevation:.12,
  materials:{interior:{id:'paving'}},features:[
   {id:'ledge',kind:'ledge',polygon:square(1,1,8,5),depth_in:12},
   {id:'steps',kind:'steps',polygon:square(1,14,7,7),entry_edge:0,treads:3},
   {id:'flush',kind:'spa',polygon:square(24,16,8),mode:'flush',depth_in:36},
   ...(raised?[{id:'raised',kind:'spa',polygon:square(24,1,8),mode:'raised',raise_in:18,depth_in:36,spillover:false}]:[])]}},
 effect_fixtures:sourced?[effect]:[]});
const compile=material=>{const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,
 fragmentShader:THREE.ShaderLib.standard.fragmentShader};material.onBeforeCompile(shader,{});return shader;};
const all=group=>{const found=[];group.traverse(o=>{if(o.isMesh)found.push(o);});return found;};
const poolDraws=group=>all(group).filter(o=>o.userData.yardPart==='pool').length;
let baselineYard;
async function headYard(){
 if(baselineYard)return baselineYard;
 const urls=new Map();for(const [path,original] of Object.entries(input.baseline)){
  const source=original.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
   const target=new URL(s,file(path)).href,child=Object.keys(input.baseline).find(p=>file(p)===target);
   return a+(child?'water-baseline:'+child:target)+b;});
  urls.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 }
 registerHooks({resolve(spec,ctx,next){return spec.startsWith('water-baseline:')?{url:urls.get(spec.slice(15)),shortCircuit:true}:next(spec,ctx);}});
 baselineYard=await import(urls.get('static/twin/twin_yard.js'));return baselineYard;
}
const rowFor=(water,id='pool')=>water.rows.find(row=>row.body.id===id);
const waterFor=async(p,tier='medium')=>(await Y.buildYard(p,kit(),tier)).group.userData.water;
function motionAt(shader,p){
 // Execute the generated selector's scalar GLSL control flow as JavaScript.
 // No vector arithmetic is involved; only its local type declarations differ.
 const start=shader.fragmentShader.indexOf('vec3 waterMotionAt(vec2 p) {');assert.ok(start>=0);
 const open=shader.fragmentShader.indexOf('{',start);let end=open+1,depth=1;
 while(depth){const c=shader.fragmentShader[end++];if(c==='{')depth++;if(c==='}')depth--;}
 const body=shader.fragmentShader.slice(open+1,end-1).replace(/\b(bool|int|vec2)\b/g,'let');
 const entries=Object.entries(shader.uniforms).filter(([key])=>key.startsWith('water'));
 return new Function(...entries.map(([key])=>key),'p',body)(...entries.map(([,u])=>u.value),new THREE.Vector2(...p));
}
await test('zero_chop_matches_shipped_uniforms_on_every_tier',async()=>{
 const old=await headYard();
 for(const tier of ['low','medium','high','max'])for(const sourced of [false,true]){
  const p=plan(true,sourced),before=(await old.buildYard(p,kit(),tier)).group.userData.water,after=await waterFor(p,tier);
  for(const time of [0,1,10]){
   before.update([],time);after.update([],time);
   for(const name of ['surfaces','submerged']){
    assert.equal(after[name].length,before[name].length);
    after[name].forEach((row,i)=>{
     for(const [key,u] of Object.entries(before[name][i].uniforms))assert.deepEqual(row.uniforms[key].value,u.value,key);
     assert.deepEqual(row.uniforms.waterMotion.value.toArray(),[0,0,0]);
     const shader=compile(row.material);assert.equal(shader.uniforms.waterMotion,row.uniforms.waterMotion);
    });
   }
  }
 }
});
await test('chop_averages_unique_wet_fixtures_and_excludes_steam_and_mist',async()=>{
 const p=plan();p.effect_fixtures=['fountain','bubbler','deck_jet','steam','mist'].map((type,i)=>({...effect,
  id:type,type,at:[12+i,10,0],entity:'switch.'+type}));
 const water=await waterFor(p),fx=buildEffects(p),row=rowFor(water);
 water.update(fx.fixtures,0);
 let states={'switch.fountain':{state:'on'},'switch.steam':{state:'on'},'switch.mist':{state:'on'}};
 fx.update(states,false,0);fx.update(states,false,1);water.update(fx.fixtures,1);
 assert.equal(row.body.fixtures.length,3);near(row.chop.target,Math.sqrt(1/3));
 states=Object.fromEntries(p.effect_fixtures.map(f=>[f.entity,{state:'on'}]));
 fx.update(states,false,1);fx.update(states,false,2);water.update(fx.fixtures,2);near(row.chop.target,1);
 const vapour={...p,effect_fixtures:p.effect_fixtures.filter(f=>['steam','mist'].includes(f.type))};
 const quiet=await waterFor(vapour);quiet.update(buildEffects(vapour).fixtures,100);
 assert.equal(quiet.rows.length,0);assert.equal(quiet.simulations.size,0);
 assert.ok([...quiet.surfaces,...quiet.submerged].every(r=>r.uniforms.waterMotion.value.x===0));
 assert.equal(Y.yardPartKeys(vapour,kit(),'medium').pool,Y.yardPartKeys({...p,effect_fixtures:[]},kit(),'medium').pool);
});
await test('chop_counts_a_line_once_and_keeps_fixtures_beyond_the_contact_budget',async()=>{
 const p=plan();p.effect_fixtures=[{...effect,id:'fall',type:'waterfall',shape:'line',at:undefined,
  path:[[4,8,3],[8,8,3],[12,8,3]],facing:'out'},...Array.from({length:8},(_,i)=>({...effect,id:'point'+i,
   at:[10+i,12,0],entity:'switch.off'}))];
 const water=await waterFor(p),fx=buildEffects(p),row=rowFor(water);
 water.update(fx.fixtures,0);assert.equal(row.body.sources.length,8);assert.equal(row.body.fixtures.length,9);
 near(row.chop.target,Math.sqrt(1/9));
});
await test('chop_uses_the_real_eased_fixture_amplitude',async()=>{
 const p=plan();p.effect_fixtures=[{...effect,entity:'switch.pump',sensor:'sensor.rpm',sensor_min:0,sensor_max:100}];
 const water=await waterFor(p),fx=buildEffects(p),row=rowFor(water);
 const states={'switch.pump':{state:'on'},'sensor.rpm':{state:'20'}};
 fx.update(states,false,0);water.update(fx.fixtures,0);fx.update(states,false,.5);water.update(fx.fixtures,.5);
 const pose=fx.fixtures[0];near(row.chop.target,Math.sqrt(pose.opacity*(.25+.75*pose.t)));
 assert.ok(row.chop.target>0&&row.chop.target<1);
 fx.update({},true,1);water.update(fx.fixtures,1);near(row.chop.target,0);
});
await test('chop_eases_over_seconds_both_ways_and_integrates_phase_without_frame_rate_drift',async()=>{
 const p=plan(),fx=buildEffects(p),water=await waterFor(p),other=await waterFor(p),row=rowFor(water);
 water.update(fx.fixtures,0);other.update(fx.fixtures,0);
 water.update(fx.fixtures,1/60);near(row.uniforms.waterMotion.value.x,1-Math.exp(-1/180));
 assert.ok(row.uniforms.waterMotion.value.x<.01);
 water.update(fx.fixtures,3);near(row.uniforms.waterMotion.value.x,1-Math.exp(-1));
 water.update(fx.fixtures,9);other.update(fx.fixtures,9);
 row.uniforms.waterMotion.value.toArray().forEach((v,i)=>near(v,rowFor(other).uniforms.waterMotion.value.getComponent(i)));
 const motion=row.uniforms.waterMotion.value.clone();
 near(motion.y,(9-3*(1-Math.exp(-3)))*S.CHOP_WAVE_SPEED_GAIN);
 near(motion.z,(9-3*(1-Math.exp(-3)))*U.CHOP_CAUSTIC_SPEED_GAIN);
 water.update([],9);near(row.uniforms.waterMotion.value.x,motion.x);
 water.update([],9+1/60);assert.ok(row.uniforms.waterMotion.value.x>.9);
 water.update([],12);near(row.uniforms.waterMotion.value.x,motion.x/Math.E);
 water.update([],8);near(row.uniforms.waterMotion.value.x,motion.x/Math.E);
 water.update([],NaN);assert.ok(row.uniforms.waterMotion.value.toArray().every(Number.isFinite));
});
await test('low_chop_holds_a_still_pose_and_never_schedules_or_renders',async()=>{
 const p=plan(),water=await waterFor(p,'low'),fx=buildEffects(p,{tier:'low'});
 let requests=0,draws=0;const raf=globalThis.requestAnimationFrame;
 globalThis.requestAnimationFrame=()=>{requests++;};
 try{
  const renderer={render(){draws++;}};water.update(fx.fixtures,0,{renderer});
  const snapshot=JSON.stringify([...water.surfaces,...water.submerged].map(r=>r.uniforms));
  for(const seconds of [1/60,3,30])water.update(fx.fixtures,seconds,{renderer});
  assert.equal(JSON.stringify([...water.surfaces,...water.submerged].map(r=>r.uniforms)),snapshot);
  assert.deepEqual(rowFor(water).uniforms.waterMotion.value.toArray(),[1,0,0]);
  assert.equal(requests,0);assert.equal(draws,0);assert.equal(water.simulations.size,0);
  water.update([],31,{renderer});assert.deepEqual(rowFor(water).uniforms.waterMotion.value.toArray(),[0,0,0]);
 }finally{globalThis.requestAnimationFrame=raf;}
});
await test('pool_and_inset_spas_have_independent_chop_without_splitting_shared_floor_draws',async()=>{
 const old=await headYard();
 for(const tier of ['low','medium','high','max']){
  const p=plan();p.effect_fixtures=[effect,{...effect,id:'spa-bubbler',type:'bubbler',at:[28,20,0],entity:'switch.spa'},
   {...effect,id:'raised-jet',type:'spa_jet',at:[28,5,2],entity:'switch.raised'}];
  const yard=await Y.buildYard(p,kit(),tier),water=yard.group.userData.water,fx=buildEffects(p,{tier});
  water.update(fx.fixtures,0);water.update(fx.fixtures,30);
  near(rowFor(water).chop.target,1);near(rowFor(water,'flush').chop.target,0);near(rowFor(water,'raised').chop.target,0);
  assert.equal(poolDraws(yard.group),poolDraws((await old.buildYard(p,kit(),tier)).group));
  for(const row of water.submerged){
   const shader=compile(row.material);
   for(const [key,u] of Object.entries(row.uniforms))assert.equal(shader.uniforms[key],u);
  }
  if(tier==='low'||tier==='medium'){
   const shared=water.submerged.find(r=>r.uniforms.waterRegionMotion0);assert.ok(shared);
   const ids=W.waterBodies(p).filter(b=>b.height===rowFor(water).body.height).map(b=>b.id);
   assert.deepEqual(ids,['flush','pool']);
   ids.forEach((id,i)=>{
    assert.equal(shared.uniforms['waterRegionMotion'+i],rowFor(water,id).uniforms.waterMotion);
    assert.deepEqual(shared.uniforms['waterRegionPolygon'+i].value.map(v=>v.toArray()),rowFor(water,id).body.polygon);
   });
   const shader=compile(shared.material);
   assert.equal(motionAt(shader,[28,20]),rowFor(water,'flush').uniforms.waterMotion.value);
   assert.equal(motionAt(shader,[16,10]),rowFor(water).uniforms.waterMotion.value);
  }
  const states={'switch.spa':{state:'on'}};fx.update(states,false,30);fx.update(states,false,31);water.update(fx.fixtures,31);
  near(rowFor(water,'flush').chop.target,1);near(rowFor(water,'raised').chop.target,0);
 }
});
await test('a_fall_off_a_spa_rim_drives_pool_chop_only',async()=>{
 const p=plan();p.effect_fixtures=[{...effect,id:'rim-fall',type:'waterfall',shape:'line',at:undefined,
  path:[[24,8,2],[24,1,2]],facing:'out'}];
 const water=await waterFor(p),fx=buildEffects(p);water.update(fx.fixtures,0);water.update(fx.fixtures,3);
 assert.deepEqual(water.rows.map(r=>r.body.id),['pool']);near(rowFor(water).chop.target,1);
 assert.ok(rowFor(water).uniforms.waterMotion.value.x>.6);
});
for(const tier of ['low','medium','high','max'])await test('all_water_and_submerged_surfaces_'+tier,async()=>{
 const p=plan(),yard=await Y.buildYard(p,kit(),tier),water=yard.group.userData.water;
 assert.ok(water);assert.equal(water, yard.group.userData.ripples);
 const surfaces=yard.group.userData.waterSurfaces;assert.ok(surfaces.length>=3);
 assert.deepEqual([...new Set(surfaces.map(m=>m.userData.pieceId))].sort(),['flush','pool','raised']);
 for(const mesh of surfaces){assert.ok(mesh.material.userData.waterSurface);const shader=compile(mesh.material);
  assert.ok(shader.fragmentShader.includes('waterFresnel'));assert.ok(shader.fragmentShader.includes('waterSlope'));
  assert.ok(shader.fragmentShader.includes('normal = normalize(normal +'));
  assert.equal(shader.uniforms.waterTime,mesh.material.userData.waterSurface.waterTime);
 }
 const bodies=W.waterBodies(p),levels=bodies.map(b=>b.height*.3048);
 assert.ok(water.submerged.length>=2);
 for(const row of water.submerged){const shader=compile(row.material);assert.ok(shader.fragmentShader.includes('cosRefracted'));
  assert.ok(shader.fragmentShader.includes('directLight.color *='));assert.ok(levels.some(level=>Math.abs(level-row.uniforms.waterLevel.value)<1e-6));
 }
 assert.ok(water.submerged.some(row=>Math.abs(row.uniforms.waterLevel.value-levels[0])<1e-6));
 const raised=bodies.find(b=>b.id==='raised');assert.ok(water.submerged.some(row=>Math.abs(row.uniforms.waterLevel.value-raised.height*.3048)<1e-6));
 const owns=(mesh,id,part=null)=>(mesh.geometry.userData.snapRanges||[]).some(range=>range.pieceId===id&&(!part||range.part===part));
 const poolFloor=all(yard.group).find(mesh=>owns(mesh,'pool')&&mesh.material.userData.underwater&&
  (mesh.geometry.userData.snapRanges||[]).some(range=>range.pieceId==='pool'&&Array.from({length:range.count},(_,i)=>range.start+i).some(i=>Math.abs(mesh.geometry.attributes.position.getY(i)+5)<1e-6)));
 assert.ok(poolFloor,'merged pool floor ownership survives');
 near(poolFloor.material.userData.underwater.waterLevel.value,bodies.find(body=>body.id==='pool').height*.3048);
 const raisedParts=all(yard.group).filter(mesh=>owns(mesh,'raised')&&mesh.material.userData.underwater);
 assert.ok(raisedParts.some(mesh=>Math.abs(mesh.material.userData.underwater.waterLevel.value-raised.height*.3048)<1e-6),'raised spa basin uses spa level');
 assert.ok(raisedParts.some(mesh=>Math.abs(mesh.material.userData.underwater.waterLevel.value-bodies[0].height*.3048)<1e-6),'raised spa outside wall uses pool level');
 yard.group.updateMatrixWorld(true);
 for(const [x,y,id] of [[16,12,'pool'],[28,20,'flush'],[28,5,'raised']]){
  const hits=new THREE.Raycaster(new THREE.Vector3(x,10,-y),new THREE.Vector3(0,-1,0)).intersectObjects(yard.group.children,true);
  const floor=hits.find(hit=>hit.object.material.userData.underwater);
  assert.ok(floor,'ray reaches the '+id+' basin');
  near(floor.object.material.userData.underwater.waterLevel.value,bodies.find(body=>body.id===id).height*.3048);
 }
 water.update([],2,{sun:0,sunDirection:new THREE.Vector3(0,1,0)});
 const times=[...water.surfaces,...water.submerged].map(row=>row.uniforms.waterTime.value);
 assert.ok(times.every(time=>time===(tier==='low'?0:2)));
 assert.ok(water.submerged.every(row=>row.uniforms.waterSun.value===0));
 water.update([],5,{sun:3});assert.ok([...water.surfaces,...water.submerged].every(row=>row.uniforms.waterTime.value===(tier==='low'?0:5)));
 assert.equal(water.simulations.size,['high','max'].includes(tier)?1:0);
 if(water.simulations.size)assert.ok(water.simulations.has('pool'));
});
await test('unsourced_bodies_share_clones_and_outside_paving_stays_original',async()=>{
 const cache=new Map(),yard=await Y.buildYard(plan(false,false),kit(),'medium',{materials:cache});
 const water=yard.group.userData.water;assert.ok(water);assert.equal(yard.group.userData.ripples,undefined);assert.equal(water.simulations.size,0);
 assert.equal(new Set(yard.group.userData.waterSurfaces.map(m=>m.material)).size,1);
 const outside=all(yard.group).filter(o=>o.userData.yardPart==='hardscape');assert.ok(outside.length);
 for(const mesh of outside){assert.equal(mesh.material.userData.underwater,undefined);assert.ok([...cache.values()].includes(mesh.material));}
 const originals=outside.map(m=>m.material),keys=originals.map(m=>m.customProgramCacheKey());
 const again=await Y.buildYard(plan(false,false),kit(),'medium',{materials:cache});
 assert.deepEqual(all(again.group).filter(o=>o.userData.yardPart==='hardscape').map(o=>o.material),originals);
 assert.deepEqual(originals.map(m=>m.customProgramCacheKey()),keys);
});
await test('surface_and_underwater_chain_library_hooks_and_clone_shared_uniforms',()=>{
 const source=new THREE.MeshStandardMaterial({color:'#123456',roughness:.7,opacity:.65,map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture()});
 source.onBeforeCompile=shader=>{shader.uniforms.previous={value:42};};source.customProgramCacheKey=()=> 'library:bake';
 const body={id:'test',height:2,sources:[{a:[1,2],b:[1,2]}]};
 for(const row of [S.surfaceMaterial(source,body,{tier:'high'}),U.underwaterMaterial(source,body,{tier:'high'})]){
  const m=row.material,copy=m.clone(),a=compile(m),b=compile(copy);
  assert.notEqual(m,source);assert.equal(m.map,source.map);assert.equal(m.normalMap,source.normalMap);assert.equal(m.roughnessMap,source.roughnessMap);
  assert.equal(m.roughness,.7);assert.equal('transmission' in m,false);assert.ok(m.customProgramCacheKey().startsWith('library:bake|'));
  assert.equal(copy.onBeforeCompile,m.onBeforeCompile);assert.equal(copy.customProgramCacheKey(),m.customProgramCacheKey());
  assert.equal(a.uniforms.previous.value,42);assert.equal(b.uniforms.previous.value,42);
  for(const [key,u] of Object.entries(row.uniforms)){assert.equal(a.uniforms[key],u);assert.equal(b.uniforms[key],u);}
  if(row.uniforms.waterBaseOpacity){copy.opacity=.25;const faded=compile(copy);
   assert.equal(faded.uniforms.waterBaseOpacity,row.uniforms.waterBaseOpacity);assert.equal(row.uniforms.waterBaseOpacity.value,source.opacity);
   const expression=faded.fragmentShader.match(/diffuseColor\.a \*= ([^;]*waterBaseOpacity[^;]*);/);assert.ok(expression,'selection/floor alpha modulates the optical alpha');
   const factor=new Function('waterFresnel','waterBaseOpacity','mix','return '+expression[1])(.02,source.opacity,(a,b,t)=>a*(1-t)+b*t);
   const native=source.opacity*.8*factor,ghost=copy.opacity*.8*factor;near(ghost/native,copy.opacity/source.opacity);
   near(native,.8*(.30+(.92-.30)*.02));}
 }
 assert.equal(source.userData.waterSurface,undefined);assert.equal(source.userData.underwater,undefined);
});
await test('every_shader_patch_requires_real_three_anchor',()=>{
 // Proxy String.replace so an accidentally stale replacement cannot silently pass.
 const replace=String.prototype.replace;let checked=0;
 String.prototype.replace=function(anchor,value){if(typeof anchor==='string'){assert.ok(this.includes(anchor),'missing replacement anchor '+anchor);checked++;}return replace.call(this,anchor,value);};
 try{for(const tier of ['low','medium','high','max'])for(const simulation of [null,SIM.createWaterSimulation({polygon:square(0,0,20),height:0})]){
  compile(S.surfaceMaterial(new THREE.MeshStandardMaterial(),{height:0,sources:[{}]},{tier,simulation}).material);
  compile(U.underwaterMaterial(new THREE.MeshStandardMaterial(),{height:0},{tier,simulation}).material);
  simulation?.dispose();
 }}finally{String.prototype.replace=replace;}
 assert.ok(checked>60,checked);
});
await test('unlit_replacements_compile_real_matcap_optics_share_uniforms_and_restore',()=>{
 for(const tier of ['low','medium','high','max']){
  const source=new THREE.MeshStandardMaterial({map:new THREE.Texture(),normalMap:new THREE.Texture(),roughnessMap:new THREE.Texture()});
  const body={id:'body',height:2,sources:[{}]},simulation=tier==='high'||tier==='max'?SIM.createWaterSimulation({polygon:square(0,0,20),height:2}):null;
  const rows=[S.surfaceMaterial(source,body,{tier,simulation}),U.underwaterMaterial(source,body,{tier,simulation})];
  const group=new THREE.Group(),materials=rows.flatMap(row=>[row.material,row.material.clone()]);
  for(const material of materials){const mesh=new THREE.Mesh(new THREE.PlaneGeometry(1,1),material);mesh.castShadow=mesh.receiveShadow=true;group.add(mesh);}
  const unlit=createUnlit();
  try{
   unlit.apply(group);
   group.children.forEach((mesh,index)=>{
    const row=rows[Math.floor(index/2)],m=mesh.material;assert.ok(m.isMeshMatcapMaterial);assert.equal(mesh.castShadow,false);
    assert.ok(m.customProgramCacheKey().endsWith('|matcap'));assert.equal(m.map,source.map);
    const shader={uniforms:{},vertexShader:THREE.ShaderLib.matcap.vertexShader,fragmentShader:THREE.ShaderLib.matcap.fragmentShader};
    m.onBeforeCompile(shader,{});
    for(const [key,u] of Object.entries(row.uniforms))assert.equal(shader.uniforms[key],u);
    row.uniforms.waterTime.value=17;assert.equal(shader.uniforms.waterTime.value,17);
    if(index<2){assert.ok(shader.fragmentShader.includes('waterFresnel'));assert.ok(shader.fragmentShader.includes('rippleSlope'));assert.ok(!shader.fragmentShader.includes('roughnessFactor = clamp'));}
    else {assert.ok(shader.fragmentShader.includes('cosRefracted'));assert.ok(shader.fragmentShader.includes('vec3 attenuation'));assert.ok(!shader.fragmentShader.includes('directLight.color *='));}
   });
   unlit.restore();group.children.forEach((mesh,index)=>{assert.equal(mesh.material,materials[index]);assert.equal(mesh.castShadow,true);assert.equal(mesh.receiveShadow,true);});
  }finally{unlit.dispose();simulation?.dispose();}
 }
});
await test('unrelated_yard_edit_reuses_pool_meshes_controller_and_uniform_keys',async()=>{
 const p=plan(),first=await Y.buildYard(p,kit(),'high'),water=first.group.userData.water;
 const before=first.group.children.filter(o=>o.userData.yardPart==='pool'),key=Y.yardPartKeys(p,kit(),'high').pool;
 water.update([],900,{sun:0});assert.equal(Y.yardPartKeys(p,kit(),'high').pool,key);
 const next=structuredClone(p);next.site.hardscape[0].polygon[1][0]++;
 assert.equal(Y.yardPartKeys(next,kit(),'high').pool,key);
 const second=await Y.buildYard(next,kit(),'high',{previous:first.group,materials:new Map(first.group.userData.materials)});
 second.group.userData.adoptParts();
 assert.equal(second.group.userData.water,water);assert.deepEqual(second.group.children.filter(o=>o.userData.yardPart==='pool'),before);
});
await test('mounted_simulations_live_through_reuse_and_dispose_on_removal_and_view_close',async()=>{
 location.search='?test=1&tier=high';const p=plan(),view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'high',bake:false});
 let closed=false;
 try{
  const controller=view.scene.getObjectByName('yard').userData.water,simulation=controller.simulations.get('pool');assert.ok(simulation);
  let removed=0;const release=simulation.dispose.bind(simulation);simulation.dispose=()=>{removed++;release();};
  const unrelated=structuredClone(p);unrelated.site.hardscape[0].polygon[1][0]++;
  await view.rebuild(unrelated);assert.equal(view.scene.getObjectByName('yard').userData.water,controller);assert.equal(removed,0);
  const dry={...unrelated,effect_fixtures:[]};await view.rebuild(dry);assert.ok(removed>=1,'source removal disposes its simulation');assert.equal(view.scene.getObjectByName('yard').userData.water.simulations.size,0);
  await view.rebuild(unrelated);const next=view.scene.getObjectByName('yard').userData.water.simulations.get('pool');assert.ok(next);assert.notEqual(next,simulation);
  let disposed=0;const finish=next.dispose.bind(next);next.dispose=()=>{disposed++;finish();};
  view.dispose();closed=true;assert.ok(disposed>=1,'closing the mounted view disposes its simulation');
 }finally{if(!closed)view.dispose();}
});
await test('simulation_masks_holes_concavities_and_aspect_and_clamps_steps',()=>{
 const body={polygon:[[0,0],[20,0],[20,5],[10,5],[10,10],[0,10]],holes:[square(2,2,4)]};
 const size=SIM.simulationSize(body);assert.equal(size.width,256);assert.equal(size.height,128);
 const mask=SIM.rasterizeMask(body,20,10),wet=(x,y)=>mask[(y*20+x)*4];
 assert.equal(wet(0,0),255);assert.equal(wet(3,3),0);assert.equal(wet(15,8),0);assert.equal(wet(8,8),255);
 assert.equal(SIM.sourceDistance([4,3],[1,1,7,1]),2);assert.equal(SIM.sourceDistance([4,5],[4,5,4,5]),0);
 assert.equal(SIM.sourceDistance([10,1],new THREE.Vector4(1,1,7,1)),3);
 assert.equal(SIM.stepCount(0).steps,0);assert.equal(SIM.stepCount(1/120).steps,0);
 assert.equal(SIM.stepCount(1/120,1/120).steps,1);
 for(const dt of [-1,0,1/60,.5,100,NaN,Infinity]){const result=SIM.stepCount(dt);assert.ok(result.steps>=0&&result.steps<=2);assert.ok(result.accumulator>=0&&result.accumulator<1/60+1e-8);}
});
await test('simulation_preserves_renderer_state_clamps_passes_and_disposes',()=>{
 const state={target:{original:true},viewport:new THREE.Vector4(3,4,500,300),scissor:new THREE.Vector4(1,2,9,8),scissorTest:true,color:new THREE.Color('#123456'),alpha:.4};
 let passes=0,disposed=0;
 const renderer={autoClear:true,xr:{enabled:true},info:{autoReset:true,render:{calls:17,triangles:300,frame:9}},
  getContext:()=>({FRAMEBUFFER:1,FRAMEBUFFER_COMPLETE:2,getExtension:()=>true,checkFramebufferStatus:()=>2}),
  getRenderTarget:()=>state.target,setRenderTarget:t=>{state.target=t;if(t&&!t.original&&!t.__watched){t.__watched=true;t.addEventListener('dispose',()=>disposed++);}},
  getViewport:v=>v.copy(state.viewport),setViewport:(...v)=>{state.viewport=v.length===1?v[0].clone():new THREE.Vector4(...v);},
  getScissor:v=>v.copy(state.scissor),setScissor:v=>state.scissor=v.clone(),getScissorTest:()=>state.scissorTest,setScissorTest:v=>state.scissorTest=v,
  getClearColor:c=>c.copy(state.color),getClearAlpha:()=>state.alpha,setClearColor:(c,a)=>{state.color=new THREE.Color(c);state.alpha=a;},clear(){},
  render(scene){passes++;this.info.render.calls++;assert.equal(scene.children.length,1);assert.ok(scene.children[0].material.isShaderMaterial);
   assert.deepEqual(scene.children[0].material.uniforms.rippleLines.value[0].toArray(),[5,7,5,7]);}};
 const original=JSON.stringify(state),stats={...renderer.info.render},sim=SIM.createWaterSimulation({polygon:square(0,0,30),height:0});
 const u={rippleStrength:{value:[1,0,0,0,0,0,0,0]},rippleLines:{value:[new THREE.Vector4(5,7,5,7),...Array.from({length:7},()=>new THREE.Vector4())]}};
 sim.update(renderer,1,u);assert.equal(passes,1);assert.equal(sim.uniforms.waterFieldActive.value,1);
 const first=sim.uniforms.waterField.value;sim.update(renderer,30,u);assert.equal(passes,3);assert.equal(sim.uniforms.waterField.value,first,'two steps ping-pong back');
 assert.equal(JSON.stringify(state),original);assert.deepEqual(renderer.info.render,stats);assert.equal(renderer.autoClear,true);assert.equal(renderer.xr.enabled,true);assert.equal(renderer.info.autoReset,true);
 sim.update(renderer,31,u,{mesh:{visible:false}});assert.equal(passes,3);
 sim.dispose();assert.equal(disposed,2);assert.equal(sim.uniforms.waterFieldActive.value,0);sim.update(renderer,32,u);assert.equal(passes,3);
 const failed=SIM.createWaterSimulation({polygon:square(0,0,30),height:0});renderer.render=()=>{throw Error('lost GPU context');};
 failed.update(renderer,1,u);assert.equal(failed.uniforms.waterFieldActive.value,0);assert.equal(JSON.stringify(state),original);
 assert.deepEqual(renderer.info.render,stats);assert.equal(renderer.autoClear,true);assert.equal(renderer.xr.enabled,true);failed.dispose();
});
await test('unsupported_half_float_falls_back_without_corrupting_renderer',()=>{
 const sim=SIM.createWaterSimulation({polygon:square(0,0,10),height:0});sim.update({},1,{rippleStrength:{value:[1]}});
 assert.equal(sim.uniforms.waterFieldActive.value,0);assert.equal(sim.uniforms.waterField.value,null);sim.dispose();
});
await test('pool_part_draw_counts_against_head_for_raised_flush_and_sources',async()=>{
 const old=await headYard();
 for(const tier of ['low','medium','high','max'])for(const raised of [false,true])for(const sourced of [false,true]){
  const p=plan(raised,sourced),before=poolDraws((await old.buildYard(p,kit(),tier)).group),after=poolDraws((await Y.buildYard(p,kit(),tier)).group);
  console.log(`POOL_DRAWS tier=${tier} raised=${raised} sources=${sourced} before=${before} after=${after}`);
  const extra=(raised?2:0)+(sourced&&['high','max'].includes(tier)?2:0);
  assert.ok(after<=before+extra,'at most two material splits per raised level or isolated simulation field');
 }
});
finish();
"""


def run():
    baseline = {path: subprocess.check_output(['git', 'show', 'HEAD:chauffeur/' + path],
                cwd=ROOT, encoding='utf-8') for path in
                ['static/twin/twin_yard.js', 'static/twin/pool_features.js',
                 'static/twin/effects/water_surface.js', 'static/twin/effects/underwater.js',
                 'static/twin/effects/water_ripples.js']}
    node = shutil.which('node')
    assert node, 'Node is required'
    scratch = ROOT / '.tmp-effects'
    scratch.mkdir(exist_ok=True)
    tag = 'water-surface-' + uuid.uuid4().hex
    script, payload = scratch / (tag + '.mjs'), scratch / (tag + '.json')
    try:
        script.write_text(DRIVER, encoding='utf-8')
        payload.write_text(json.dumps({'root': ROOT.as_posix(), 'editable': True,
                                      'baseline': baseline}), encoding='utf-8')
        result = subprocess.run([node, str(script), str(payload)], capture_output=True,
                                text=True, encoding='utf-8', timeout=180)
        print(result.stdout + result.stderr)
        return result.returncode
    finally:
        script.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
