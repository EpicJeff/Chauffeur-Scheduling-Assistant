"""Run effect lighting, lamp/bake integration and receiving water with real Three.js."""
import sys
from test_twin_effect_visuals_js import run
import test_twin_effect_visuals_js as harness
from test_twin_untouched_house_js import COMMON

harness.DRIVER = COMMON + r"""
const E=await import(file('static/twin/live/emitters.js'));
const W=await import(file('static/twin/effects/water_ripples.js'));
const {buildEffects}=await import(file('static/twin/effects/index.js'));
const {bakeLights}=await import(file('static/twin/bake/runtime.js'));
const {emitterSamples}=await import(file('static/twin/bake/fixture_terms.js'));
const {mountLive,keepLive}=await import(file('static/twin/live/live.js'));
const {mountModes}=await import(file('static/twin/live/modes.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const Y=await import(file('static/twin/twin_yard.js'));
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const f=(type,more={})=>({id:'effect:'+type,type,shape:'point',ref:'absolute',at:[10,10,0],...more});
const plan=(...effects)=>({buildings:[],site:{lot:square(0,0,80),pool:{id:'pool',polygon:square(0,0,30),depth:4,
 features:[{id:'spa',kind:'spa',polygon:square(20,20,6),mode:'raised',raise_in:12}]}},effect_fixtures:effects});
const empty={markers:[],devices:[],rooms:[]};
const emit=(p,states={},rows)=>E.resolveEmitters(empty,states,p,{effectRows:rows});
const compile=m=>{const shader={uniforms:{},vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader};m.onBeforeCompile(shader,{});return shader;};
await test('point_fire_is_one_warm_half_output_pit_source_above_flames',()=>{
 const p=plan(f('fire')),e=emit(p)[0];assert.equal(emit(p).length,1);assert.equal(e.fire_pit,true);
 assert.deepEqual(e.rgb,[255,154,60]);assert.deepEqual(e.at,[10,10,2.25]);assert.equal(e.range,18);
 close(e.cd,503*.5/(4*Math.PI));close(e.intensityScale,.5);
});
await test('line_fire_samples_by_arc_length_halves_each_and_caps_at_six',()=>{
 for(const [path,count] of [[[[0,0,2],[20,0,2]],5],[[[0,0,2],[10,0,2],[10,10,2]],5],[[[0,0,2],[100,0,2]],6]]){
  const p=plan(f('fire',{shape:'line',at:undefined,path,facing:'out'})),rows=emit(p);
  assert.equal(rows.length,count);assert.ok(rows.every(e=>e.shape==='point'&&e.fire_pit));
  rows.forEach(e=>{close(e.cd,503*.25/(4*Math.PI));close(e.intensityScale,.25);});
  if(path.length===2){close(rows[0].at[0],(path[1][0]/count)/2);close(rows.at(-1).at[0],path[1][0]-(path[1][0]/count)/2);}
 }
});
await test('fire_state_staleness_opacity_and_eased_strength_drive_real_output',()=>{
 const p=plan(f('fire',{entity:'switch.fire'})),on={'switch.fire':{state:'on'}};
 assert.equal(emit(p)[0].on,false);assert.equal(emit(p,{'switch.fire':{state:'off'}})[0].cd,0);
 assert.equal(emit(p,{states:on,stale:true})[0].on,false);
 assert.equal(emit(p,{'switch.fire':{state:'on',stale:true}})[0].on,false);
 const fx=buildEffects(p);fx.update(on,false,1);fx.update(on,false,1.5);
 close(emit(p,on,fx.fixtures)[0].brightness,.5);
 for(const [active,opacity,t,level] of [[true,0,1,0],[false,1,1,0],[true,.6,0,.2],[true,.6,1,.6]]){
  Object.assign(fx.fixtures[0],{active,opacity,t});const e=emit(p,on,fx.fixtures)[0];
  close(e.brightness,level);close(e.cd,503*.5*level/(4*Math.PI));assert.equal(e.on,level>0);
 }
});
await test('always_on_and_sensor_only_fire_light_without_a_switch',()=>{
 const p=plan(f('fire'));assert.equal(emit(p,{stale:true})[0].on,true);
 p.effect_fixtures[0].sensor='sensor.fire';p.effect_fixtures[0].sensor_min=0;p.effect_fixtures[0].sensor_max=100;
 assert.equal(emit(p)[0].on,false);close(emit(p,{'sensor.fire':{state:'50'}})[0].brightness,2/3);
});
await test('water_adds_no_emitter_or_bake_light_and_signatures_ignore_level',()=>{
 const p=plan(),before=JSON.stringify(emit(p)),bake=JSON.stringify(bakeLights(empty,null,p));
 p.effect_fixtures=[f('fountain'),f('bubbler'),f('waterfall',{shape:'line',at:undefined,path:[[0,0,3],[5,0,3]]})];
 assert.equal(JSON.stringify(emit(p)),before);assert.equal(JSON.stringify(bakeLights(empty,null,p)),bake);
 p.effect_fixtures=[f('fire',{entity:'switch.fire'})];
 assert.equal(E.emitterSignature(emit(p)),E.emitterSignature(emit(p,{'switch.fire':{state:'on'}})));
});
await test('bake_uses_pit_point_and_sum_sampling_with_separate_effect_channels',()=>{
 const p=plan(f('fire',{id:'one',entity:'switch.fire'}),f('fire',{id:'two',shape:'line',at:undefined,path:[[0,0,2],[20,0,2]],facing:'out',entity:'switch.fire'}));
 const rows=bakeLights(empty,null,p);assert.equal(rows.length,2);assert.equal(rows[0].kind,0);assert.equal(rows[1].kind,3);
 assert.notEqual(rows[0].device,rows[1].device);
 const samples=emitterSamples(rows[1].emitters);close(samples.reduce((s,p)=>s+p.cd*p.weight,0),5*503*.25/(4*Math.PI));
});
await test('low_tier_fire_is_steady_at_the_right_level',()=>{
 const p=plan(f('fire',{strength:.25})),fx=buildEffects(p,{tier:'low'});fx.update({},true,1);
 const a=emit(p,{},fx.fixtures);fx.update({},true,19);assert.deepEqual(emit(p,{},fx.fixtures),a);
 close(a[0].brightness,.5);assert.ok(fx.group.children[0].children.every(m=>m.material.uniforms.time.value===0));
});
await test('offline_mount_reuses_real_lamp_rig_for_fire_and_keeps_switched_fire_dark',async()=>{
 location.search='?test=1';const p=fixture();p.effect_fixtures=[f('fire'),f('fire',{id:'switched',entity:'switch.fire'})];
 const view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});let live;
 try{live=await mountLive(view,{api:async()=>({ok:true,json:async()=>({available:false})})});
  assert.ok(live?.offlineEffects);view.render();const rows=live.lights();assert.equal(rows.length,2);
  close(rows[0].intensity,.5);assert.equal(rows[0].real,true);assert.equal(rows[1].intensity,0);
  const lit=[];view.scene.traverse(o=>{if(o.isPointLight&&o.intensity>0)lit.push(o);});assert.ok(lit.length>0);
  // Levels, the idle view and the energy settings call these on any mounted layer.
  live.closeRoom();live.openRoom(null,'yard');live.configureEnergy({mapping:{},cars:[]});live.configureGlance([]);
  assert.equal(live.openedRoom(),null);assert.deepEqual(live.markers(),[]);
 }finally{live?.stop();view.dispose();}
});
await test('live_modes_scale_fresh_bake_each_frame_and_turn_off_its_real_lamp',async()=>{
 const p=fixture();p.effect_fixtures=[f('fire')];location.search='?test=1';
 const view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});let modes;
 const tints=[];const id='effect-fire:effect:fire';view.bake={fresh:()=>[id],light:(...args)=>tints.push(args),stop(){}};
 const live={layout:()=>empty,peek:()=>({}),stale:()=>true,rooms:()=>[],subscribe:()=>()=>{},setMode(){}};
 try{modes=mountModes(view,live);const row=view.effects.fixtures[0];Object.assign(row,{active:true,opacity:.6,t:0});modes.draw();
  close(tints.at(-1)[2],.1);assert.equal(modes.lights()[0].real,false);
  Object.assign(row,{active:false});modes.draw();assert.equal(tints.at(-1)[2],0);
 }finally{modes?.stop();view.dispose();}
});
await test('line_fire_baked_sum_scales_once_and_steady_frames_leave_tints_alone',async()=>{
 const p=fixture();p.effect_fixtures=[f('fire',{shape:'line',at:undefined,path:[[0,0,2],[20,0,2]],facing:'out'})];
 location.search='?test=1';const view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});let modes;
 const tints=[];view.bake={fresh:()=>['effect-fire:effect:fire'],light:(...args)=>tints.push(args),stop(){}};
 const live={layout:()=>empty,peek:()=>({}),stale:()=>false,rooms:()=>[],subscribe:()=>()=>{},setMode(){}};
 try{modes=mountModes(view,live);Object.assign(view.effects.fixtures[0],{active:true,opacity:.6,t:0});modes.draw();
  close(tints.at(-1)[2],.2);const count=tints.length;modes.draw();assert.equal(tints.length,count);
  assert.ok(modes.lights().every(l=>l.baked&&!l.real));
 }finally{modes?.stop();view.dispose();}
});
await test('offline_lamp_layer_recovers_when_ha_returns_with_an_identical_empty_layout',async()=>{
 location.search='?test=1';const p=fixture();p.effect_fixtures=[f('fire')];
 const view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});let available=false;
 const api=async path=>({ok:true,json:async()=>path==='api/house/live'?{...empty,available}:path.startsWith('api/ha/card/states')?{states:{},reachable:true}: {}});
 const keeper=keepLive(view,{api}),frames=setInterval(tick,1);
 try{await keeper.check();assert.ok(keeper.live().offlineEffects);available=true;await keeper.check();
  assert.ok(keeper.live());assert.equal(keeper.live().offlineEffects,undefined);
 }finally{clearInterval(frames);keeper.live()?.stop();keeper.stop();view.dispose();}
});
await test('fountain_pool_bubbler_spa_and_waterfall_register_receiving_sources',()=>{
 const p=plan(f('fountain'),f('bubbler',{at:[23,23,1]}),f('waterfall',{shape:'line',at:undefined,path:[[4,-1,4],[12,-1,4]],facing:'in'}));
 const bodies=W.rippleSources(p);assert.equal(bodies.length,2);
 const pool=bodies.find(b=>b.id==='pool'),spa=bodies.find(b=>b.id==='spa');
 assert.equal(pool.sources.length,2);assert.equal(spa.sources.length,1);assert.deepEqual(spa.sources[0].a,[23,23]);
 assert.deepEqual(pool.sources[0].a,[10,10]);assert.deepEqual(pool.sources[1].b,[12,-1]);close(pool.height,-.25);
 assert.equal(W.rippleSources(plan(f('fountain',{at:[50,50,0]}),f('waterfall',{shape:'line',at:undefined,path:[[50,50,5],[60,50,5]]}))).length,0);
});
await test('ninth_water_source_is_ignored_nearest_centre_first',()=>{
 const effects=Array.from({length:9},(_,i)=>f('fountain',{id:'water'+i,at:[i+2,15,0]}));
 const body=W.rippleSources(plan(...effects))[0];assert.equal(body.sources.length,8);
 assert.equal(body.sources.some(s=>s.fixture.id==='water0'),false);assert.equal(body.sources[0].fixture.id,'water8');
});
await test('ripples_follow_eased_strength_and_flow_without_rebuilding_geometry',async()=>{
 const p=plan(f('fountain',{entity:'switch.water',sensor:'sensor.rpm',sensor_min:0,sensor_max:100}));
 const fx=buildEffects(p),yard=await Y.buildYard(p,kit(),'high'),r=yard.group.userData.ripples,ids=yard.group.children.map(o=>o.geometry?.uuid);
 const on={'switch.water':{state:'on'},'sensor.rpm':{state:'0'}};fx.update(on,false,1);fx.update(on,false,1.5);r.update(fx.fixtures,1.5);
 const pose=fx.fixtures[0];close(r.rows[0].uniforms.rippleStrength.value[0],pose.opacity*(.25+.75*pose.t));
 assert.ok(r.rows[0].uniforms.rippleStrength.value[0]>0);const time=r.rows[0].uniforms.rippleTime.value;
 fx.update(on,false,2);r.update(fx.fixtures,2);assert.ok(r.rows[0].uniforms.rippleTime.value>time);
 fx.update({},true,3);r.update(fx.fixtures,3);assert.equal(r.rows[0].uniforms.rippleStrength.value[0],0);
 Object.assign(pose,{active:true,opacity:0});r.update(fx.fixtures,4);assert.equal(r.rows[0].uniforms.rippleStrength.value[0],0);
 assert.deepEqual(yard.group.children.map(o=>o.geometry?.uuid),ids);
});
await test('low_water_holds_time_and_line_source_tracks_the_visual_landing_flow',async()=>{
 const p=plan(f('waterfall',{shape:'line',at:undefined,path:[[5,5,4],[12,5,4]],facing:'out'}));
 const fx=buildEffects(p,{tier:'low'}),yard=await Y.buildYard(p,kit(),'low'),r=yard.group.userData.ripples;
 fx.update({},false,1);r.update(fx.fixtures,1);const u=r.rows[0].uniforms,lines=u.rippleLines.value.map(v=>v.toArray());
 close(u.rippleStrength.value[0],1);close(u.rippleLines.value[0].y,5-(.08+1.5*.6)*(1-Math.exp(-6)));
 r.update(fx.fixtures,22);assert.equal(u.rippleTime.value,0);assert.deepEqual(u.rippleLines.value.map(v=>v.toArray()),lines);
});
await test('ripples_preserve_library_slot_maps_hooks_and_bake_viewing_clones',async()=>{
 const p=plan(f('fountain'));p.site.pool.materials={water:{id:'choice'}};
 const yard=await Y.buildYard(p,kit(),'high'),row=yard.group.userData.ripples.rows[0],m=row.material;
 assert.equal(m.userData.materialId,'choice');assert.equal(m.roughness,.7);assert.equal('transmission' in m,false);
 const shader=compile(m);assert.ok(shader.fragmentShader.includes('normal = normalize(normal +'));
 assert.ok(shader.fragmentShader.includes('diffuseColor.rgb = mix'));assert.equal(shader.uniforms.rippleTime,row.uniforms.rippleTime);
 const clone=m.clone();assert.equal(clone.customProgramCacheKey(),m.customProgramCacheKey());assert.equal(compile(clone).uniforms.rippleTime,row.uniforms.rippleTime);
 const spy=new THREE.MeshStandardMaterial();spy.onBeforeCompile=s=>{s.uniforms.previous={value:2};};spy.customProgramCacheKey=()=> 'previous';
 const patched=W.rippleMaterial(spy,row.body).material;assert.equal(compile(patched).uniforms.previous.value,2);assert.ok(patched.customProgramCacheKey().startsWith('previous|'));
});
await test('unsourced_pool_and_spa_keep_material_program_and_draws_unchanged',async()=>{
 const p=plan(),cache=new Map(),base=await Y.buildYard(p,kit(),'low',{materials:cache});
 const originals=base.group.userData.waterSurfaces.map(m=>m.material),keys=originals.map(m=>m.customProgramCacheKey());
 const withDry=await Y.buildYard({...p,effect_fixtures:[f('fountain',{at:[50,50,0]})]},kit(),'low',{materials:cache});
 assert.equal(withDry.group.userData.ripples,undefined);assert.deepEqual(withDry.group.userData.waterSurfaces.map(m=>m.material),originals);
 assert.deepEqual(originals.map(m=>m.customProgramCacheKey()),keys);assert.equal(withDry.group.children.length,base.group.children.length);
 const wet=await Y.buildYard(plan(f('fountain')),kit(),'low');
 assert.equal(wet.group.children.length,base.group.children.length+1); // shared pool/spa water separates by body, no overlay geometry
 const spa=wet.group.userData.waterSurfaces.find(m=>m.userData.kind==='spa');assert.ok(!spa.material.customProgramCacheKey().includes('water-ripples'));
});
await test('mounted_water_surface_receives_frame_updates_and_reuses_then_clears_on_edit',async()=>{
 location.search='?test=1';const p=fixture();p.effect_fixtures=[f('fountain',{at:[17,40,0]})];
 const view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'low',bake:false});
 try{view.render();const yard=view.scene.getObjectByName('yard'),r=yard.userData.ripples;assert.ok(r);close(r.rows[0].uniforms.rippleStrength.value[0],1);
  await view.rebuild({...p});assert.equal(view.scene.getObjectByName('yard').userData.ripples,r);
  await view.rebuild({...p,effect_fixtures:[]});assert.equal(view.scene.getObjectByName('yard').userData.ripples,undefined);
 }finally{view.dispose();}
});
finish();
"""

if __name__ == '__main__':
    sys.exit(run())
