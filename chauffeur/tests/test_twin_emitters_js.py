"""Execute the shared emitter resolver and its live entry point in Node, no browser.

Legacy fixture was captured by executing the placement block of main's modes.js
before implementing this resolver; its source commit is recorded in the JSON.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from test_twin_real_lights_js import DRIVER as REAL_LIGHTS_DRIVER

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url:file('static/vendor/three-r187/three.module.js'),shortCircuit:true};
  if (spec.startsWith('three/addons/')) return {url:file('static/vendor/three-r187/addons/'+spec.slice(13)),shortCircuit:true};
  return next(spec,ctx);
},load(url,ctx,next) {
  return url.endsWith('.js') ? {...next(url,{...ctx,format:'module'}),format:'module'} : next(url,ctx);
}});
let mod = {};
try { mod = await import(file('static/twin/live/emitters.js')); } catch (e) { console.log(e.message); }
const {emission,resolveEmitters,firePitEmitters,emitterSignature} = mod;
const {lightColor} = await import(file('static/twin/live/real_lights.js'));
const {gasTableLayout,firePitLayout,firePitOptions,buildFirePit} = await import(file('static/twin/fire_pits.js'));
const THREE=await import(file('static/vendor/three-r187/three.module.js'));
const close = (a,b) => assert.ok(Math.abs(a-b)<1e-10,`${a} != ${b}`);
const near = (a,b) => a.forEach((v,i)=>close(v,b[i]));
const plan = {buildings:[],site:{}};
const fixture = (id,shape,fields={}) => ({id:'fixture:'+id,shape,ref:'absolute',...fields});
const layout = (rows,meta={output_lm:503}) => ({markers:[],light_fixtures:{'light.test':rows},light_fixtures_meta:{'light.test':meta}});
const states = {'light.test':{state:'on',attributes:{}}};
const resolve = (rows,meta) => resolveEmitters(layout(rows,meta),states,plan);
const checks=[];const check=(name,fn)=>checks.push([name,fn]);

check('legacy_floor_and_ceiling_match_old_rules',()=>{
  const snapshot=JSON.parse(readFileSync(new URL(file('tests/fixtures/twin_emitters_legacy.json'))));
  const out=resolveEmitters({markers:snapshot.markers},{},snapshot.plan);
  assert.equal(out.length,snapshot.markers.length);
  for(const expected of snapshot.expected){
    const row=out.find(e=>e.device_id===expected.device_id);
    assert.equal(row.legacy,true);assert.deepEqual(row.position,expected.position);assert.equal(row.range,expected.range);
    near(row.at,[expected.position[0]/.3048,-expected.position[2]/.3048,expected.position[1]/.3048]);
    assert.equal(row.marker,snapshot.markers.find(m=>m.device_id===expected.device_id),'the emitter carries its own marker');
  }
});
check('legacy_lamp_is_a_default_point_fixture',()=>{
  const marker={kind:'light',device_id:'d1',entity_id:'light.a',at:[1,2,9]},twin={kind:'light',device_id:'d2',entity_id:'light.a',at:[3,2,9]};
  const out=resolveEmitters({markers:[marker,twin]},{'light.a':{state:'on',attributes:{brightness:128}}},plan);
  assert.equal(out.length,2);assert.equal(out[0].marker,marker);assert.equal(out[1].marker,twin,'same entity, distinct markers');
  close(out[0].output_lm_share,503*128/255);close(out[0].cd,out[0].output_lm_share/(4*Math.PI));
  const fixtureLike=resolve([fixture('p','point',{at:[1,2,3]})])[0],legacyFull=resolveEmitters({markers:[marker]},{'light.a':{state:'on',attributes:{}}},plan)[0];
  close(legacyFull.cd,fixtureLike.cd);close(legacyFull.output_lm_share,fixtureLike.output_lm_share);
});
check('switch_on_is_2700k_full',()=>{
  assert.deepEqual(emission({state:'on',attributes:{brightness:2}},'switch'),{on:true,brightness:1,rgb:lightColor({color_temp_kelvin:2700})});
  assert.equal(emission({state:'off'},'switch').on,false);
});
check('input_boolean_and_fan_are_on_off_sources',()=>{
  for(const domain of ['input_boolean','fan']){
    assert.deepEqual(emission({state:'on',attributes:{}},domain),{on:true,brightness:1,rgb:lightColor({color_temp_kelvin:2700})});
    for(const state of [{state:'off'},{state:'unavailable'},{state:'on',stale:true},null])assert.equal(emission(state,domain).on,false);
  }
});
check('tv_paused_emits_idle_does_not',()=>{
  for(const state of ['on','playing','paused']) assert.deepEqual(emission({state},'media_player'),{on:true,brightness:.3,rgb:lightColor({color_temp_kelvin:6500})});
  for(const state of ['idle','standby','off']) assert.equal(emission({state},'media_player').on,false);
});
check('unavailable_and_stale_never_emit',()=>{
  for(const domain of ['light','switch','media_player','input_boolean','fan']) for(const state of [null,{state:'unknown'},{state:'unavailable'},{state:'on',stale:true},{state:'on',reachable:false}]) {
    assert.equal(emission(state,domain).on,false);assert.equal(emission(state,domain).brightness,0);
  }
  assert.ok(resolveEmitters(layout([fixture('p','point',{at:[1,2,3]})]),{states,reachable:false},plan).every(e=>!e.on));
});
check('light_brightness_and_colour_scale_output_once',()=>{
  const l=layout([fixture('p','point',{at:[1,2,3]})]);
  const out=resolveEmitters(l,{'light.test':{state:'on',attributes:{brightness:128,rgb_color:[12,34,56]}}},plan)[0];
  assert.deepEqual(out.rgb,[12,34,56]);close(out.output_lm_share,503*128/255);close(out.cd,out.output_lm_share/(4*Math.PI));
  assert.deepEqual(emission({state:'on',attributes:{}},'light').rgb,[255,241,201]);
});
check('line_shares_sum_to_output_and_subdivision_keeps_total',()=>{
  const line=(id,a,b)=>fixture(id,'line',{path:[a,b],width_in:.5,facing:'down'});
  const whole=resolve([line('whole',[0,0,3],[40,0,3])]);
  const split=resolve([line('a',[0,0,3],[10,0,3]),line('b',[10,0,3],[40,0,3])]);
  close(split.reduce((s,e)=>s+e.output_lm_share,0),503);
  for(const e of split)close(e.luminance,whole[0].luminance);
  close(whole[0].luminance,503/(Math.PI*40*(.5/12)*.3048**2));
  const vertices=resolve([fixture('v','line',{path:[[0,0,3],[10,0,3],[40,0,3]],width_in:.5,facing:'down'})]);
  close(vertices[0].luminance,whole[0].luminance);
});
check('authored_shares_override_geometric_weights',()=>{
  const out=resolve([fixture('p','point',{at:[1,2,3],share:3}),fixture('a','area',{at:[2,3,4],size_ft:[2,2],share:1})],{output_lm:1000});
  assert.deepEqual(out.map(e=>e.output_lm_share),[750,250]);
  assert.ok(resolve([fixture('z','point',{at:[0,0,1],share:0})]).every(e=>e.output_lm_share===0&&!e.on));
});
check('spot_cd_from_cone',()=>{
  const e=resolve([fixture('s','spot',{at:[1,2,3],aim:[5,6,0],cone_deg:60,softness:.3})])[0];
  close(e.cd,503/(2*Math.PI*(1-Math.cos(Math.PI/6))));assert.deepEqual(e.aim,[5,6,0]);assert.equal(e.softness,.3);
});
check('area_luminance_from_size',()=>{
  const e=resolve([fixture('a','area',{at:[1,2,3],size_ft:[2,4],facing:'up',rotation_deg:30})])[0];
  close(e.luminance,503/(Math.PI*8*.3048**2));assert.equal(e.rotation_deg,30);
});
check('floor_ground_absolute_refs_do_not_get_legacy_offsets',()=>{
  const p={buildings:[{id:'b',base:2,levels:[{id:'L',elevation:10,ceiling:9}]}],site:{terraces:[{polygon:[[0,0],[20,0],[20,20],[0,20]],height:3,blend:0}]}};
  const rows=['floor','ground','absolute'].map(ref=>fixture(ref,'spot',{ref,building:'b',level:'L',at:[4,5,0],aim:[6,7,1],cone_deg:90}));
  const out=resolveEmitters(layout(rows),states,p);
  assert.deepEqual(out.map(e=>e.at[2]),[12,3,0]);assert.deepEqual(out.map(e=>e.aim[2]),[13,4,1]);
});
check('orphaned_and_detached_still_resolve_without_a_marker',()=>{
  const rows=[fixture('o','point',{at:[2,3,4],ref:'floor',building:'gone',level:'gone',orphaned:true}),fixture('d','line',{path:[[1,2,3],[4,5,3]],facing:'down',width_in:.5,detached:true,snap:{host:{kind:'retaining_wall',id:'gone'},edge:{from:[1,2],to:[4,5]}}})];
  const before=JSON.stringify(rows),out=resolve(rows);
  assert.equal(out.length,2);assert.equal(out[0].orphaned,true);assert.deepEqual(out[0].at,[2,3,4]);
  assert.equal(out[1].detached,true);assert.equal(out[1].path.length,2);assert.equal(JSON.stringify(rows),before);
});
check('wall_cap_run_facing_down_sits_under_the_cap_and_off_the_face',()=>{
  const p={buildings:[],site:{terraces:[{id:'pad',polygon:[[0,0],[10,0],[10,10],[0,10]],height:3,edges:[{edge:'sharp',wall:{above_in:6}}]}]}};
  const f=fixture('cap','line',{path:[[2,0,3.5],[8,0,3.5]],facing:'down',width_in:.5,snap:{host:{kind:'retaining_wall',id:'pad'},edge:{from:[0,0],to:[10,0]},t0:.2,t1:.8}});
  const before=JSON.stringify(f);const [e]=resolveEmitters(layout([f]),states,p);
  near(e.path[0],[2,-1/12,3.5-2/12]);near(e.path[1],[8,-1/12,3.5-2/12]);assert.equal(JSON.stringify(f),before);
  f.snap.edge={from:[10,0],to:[0,0]};f.path.reverse();
  near(resolveEmitters(layout([f]),states,p)[0].path[0],[8,-1/12,3.5-2/12]);
});
check('host_facing_presets_and_path_surface_outward_normal',()=>{
  const p={buildings:[],site:{hardscape:[{id:'path',kind:'path',points:[[0,0],[10,0]],width:4}]}};
  const f=fixture('path','line',{path:[[1,-2,0],[9,-2,0]],width_in:.5,snap:{host:{kind:'hardscape',id:'path'},edge:{from:[0,-2],to:[10,-2]}}});
  for(const [facing,at] of [['out',[1,-2-1/12,0]],['up',[1,-2,1/12]],['in',[1,-2+1/12,0]]]) {
    f.facing=facing;near(resolveEmitters(layout([f]),states,p)[0].path[0],at);
  }
  const area={...f,id:'fixture:area',shape:'area',at:[1,-2,0],size_ft:[2,1],facing:'down'};delete area.path;
  near(resolveEmitters(layout([area]),states,p)[0].at,[1,-2-1/12,-2/12]);
});
check('drawn_line_keeps_its_plan_path_and_sunken_pad_faces_low_side',()=>{
  // A hostless drawn line has no face to stand off: no lateral offset, only the drop.
  const f=fixture('drawn','line',{path:[[1,0,3],[9,0,3]],facing:'down',width_in:.5});
  near(resolve([f])[0].path[0],[1,0,3-2/12]);
  for(const facing of ['out','in'])near(resolve([{...f,facing}])[0].path[1],[9,0,3]);
  near(resolve([{...f,facing:'up'}])[0].path[0],[1,0,3+1/12]);
  const p={buildings:[],site:{terraces:[{id:'sunken',polygon:[[0,0],[10,0],[10,10],[0,10]],height:-3,blend:0}]}};
  f.path=[[1,0,-3],[9,0,-3]];f.snap={host:{kind:'retaining_wall',id:'sunken'},edge:{from:[0,0],to:[10,0]}};
  near(resolveEmitters(layout([f]),states,p)[0].path[0],[1,1/12,-3-2/12]);
});
check('step_runs_face_downhill_off_the_nosing',()=>{
  // Stair climbs from [0,0] to [0,10]: downhill is -y. Edge order must not matter.
  const stair={id:'st',level:'L',from:[0,0],to:[0,10],width:4,rise_to:8,risers:8};
  const p={buildings:[{id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L',elevation:0,ceiling:9}],stairs:[stair]}],site:{}};
  const f=fixture('riser','line',{path:[[-2,1.25,1],[2,1.25,1]],facing:'down',width_in:.5,snap:{host:{kind:'step',id:'st'},edge:{from:[-2,1.25],to:[2,1.25]},t0:0,t1:1}});
  for(const edge of [{from:[-2,1.25],to:[2,1.25]},{from:[2,1.25],to:[-2,1.25]}]){
    f.snap.edge=edge;const [e]=resolveEmitters(layout([f]),states,p);
    near(e.path[0],[-2,1.25-1/12,1-2/12]);near(e.normal,[0,0,-1]);
    near(resolveEmitters(layout([{...f,facing:'out'}]),states,p)[0].normal,[0,-1,0]);
  }
  // Rotating the building 90 degrees turns the run to -x, so downhill is +x.
  p.buildings[0].rotation=90;
  const g=fixture('turned','line',{path:[[-1.25,-2,1],[-1.25,2,1]],facing:'out',width_in:.5,snap:{host:{kind:'step',id:'st'},edge:{from:[-1.25,2],to:[-1.25,-2]},t0:0,t1:1}});
  near(resolveEmitters(layout([g]),states,p)[0].path[0],[-1.25+1/12,-2,1]);
});
check('fence_out_is_right_of_the_drawn_direction',()=>{
  const p={buildings:[],site:{fence:[{id:'fence',polyline:[[0,0],[10,0],[10,10]],height:6}]}};
  for(const [edge,path,at] of [[{from:[10,0],to:[0,0]},[[8,0,6],[2,0,6]],[8,-1/12,6]],[{from:[10,2],to:[10,8]},[[10,2,6],[10,8,6]],[10+1/12,2,6]]]){
    const f=fixture('fence','line',{path,facing:'out',width_in:.5,snap:{host:{kind:'fence',id:'fence'},edge,t0:0,t1:1}});
    near(resolveEmitters(layout([f]),states,p)[0].path[0],at);
  }
});
check('snapped_runs_take_the_auto_foundation_lift_from_building_hosts_only',async()=>{
  const {buildingGround}=await import(file('static/twin/twin_ground.js'));
  const b={id:'b',position:[0,0],rotation:0,base:0,foundation:{mode:'auto',offset_ft:1},levels:[{id:'L',elevation:0,ceiling:9}],rooms:[],
    walls:[{id:'w',level:'L',from:[0,0],to:[10,0]}],stairs:[]};
  const p={buildings:[b],site:{terraces:[{polygon:[[-20,-20],[40,-20],[40,40],[-20,40]],height:3,blend:0}],hardscape:[{id:'patio',polygon:[[20,0],[30,0],[30,10],[20,10]],elevation:3}]}};
  const lift=buildingGround(p,b);assert.ok(lift>3,'the auto foundation lifts the building '+lift);
  // Server frame: a wall top is base + elevation + height, with no auto lift.
  const wall=ref=>fixture('w'+ref,'line',{ref,...(ref==='floor'?{building:'b',level:'L'}:{}),path:[[2,0,ref==='ground'?6:9],[8,0,ref==='ground'?6:9]],facing:'up',width_in:.5,
    snap:{host:{kind:'wall',id:'w'},edge:{from:[0,0],to:[10,0]},t0:.2,t1:.8}});
  for(const ref of ['absolute','floor','ground'])close(resolveEmitters(layout([wall(ref)]),states,p)[0].path[0][2],9+lift+1/12);
  // Site hosts are true lot heights: a floor ref there must not add the building's lift.
  const patio=fixture('patio','line',{ref:'floor',building:'b',level:'L',path:[[20,2,3],[20,8,3]],facing:'up',width_in:.5,
    snap:{host:{kind:'hardscape',id:'patio'},edge:{from:[20,0],to:[20,10]},t0:.2,t1:.8}});
  close(resolveEmitters(layout([patio]),states,p)[0].path[0][2],3+1/12);
  // Unsnapped floor fixtures still sit on the lifted floor, as legacy markers do.
  close(resolveEmitters(layout([fixture('pt','point',{ref:'floor',building:'b',level:'L',at:[5,5,8]})]),states,p)[0].at[2],8+lift);
});
check('linear_burner_gives_line_wide_gives_area_wood_gives_point',()=>{
  const linear={id:'linear',shape:'rectangle',polygon:[[0,0],[12,0],[12,2],[0,2]],fuel:'gas',entity:'switch.fire'};
  const wide={...linear,id:'wide',polygon:[[0,0],[4,0],[4,4],[0,4]]};
  const wood={id:'wood',shape:'round',at:[5,5],radius:2,fuel:'wood',entity:'switch.fire'};
  const table=gasTableLayout(linear),[line]=firePitEmitters(linear,plan),[area]=firePitEmitters(wide,plan),[point]=firePitEmitters(wood,plan);
  assert.equal(line.shape,'line');assert.equal(line.facing,'up');assert.equal(line.entity_id,'switch.fire');
  close(Math.hypot(...line.path[1].map((v,k)=>v-line.path[0][k])),table.lineLength);
  near(line.path[0].slice(0,2),table.centre.map((v,k)=>v-table.u[k]*table.lineLength/2));
  close(line.path[0][2],firePitOptions(linear).height+table.slabThickness-.075+.07);
  assert.equal(area.shape,'area');assert.equal(area.facing,'up');assert.ok(area.size_ft.every(v=>v>0));
  assert.equal(point.shape,'point');near(point.at.slice(0,2),firePitLayout(wood).centre);
});
check('derived_emitters_match_built_burner_and_log_heights',()=>{
  for(const fuel of ['gas','wood']) {
    const pit={id:fuel,shape:'round',at:[5,5],radius:2,fuel,elevation:2};
    const group=new THREE.Group(),mat=name=>new THREE.MeshStandardMaterial({name});
    const built=buildFirePit(group,pit,2,{id:fuel,mat,plain:(name,color,extra)=>new THREE.MeshStandardMaterial({name,color,...extra})});
    const [e]=firePitEmitters(pit,plan);
    if(fuel==='wood')close(e.at[2],Math.max(...built.logs.map(log=>log.height+log.radius))+1);
    else {built.burner.geometry.computeBoundingBox();assert.ok(Math.abs(e.at[2]-built.burner.geometry.boundingBox.getCenter(new THREE.Vector3()).y)<1e-6,'Float32 burner centre matches resolved height');}
    group.traverse(o=>{o.geometry?.dispose();for(const m of o.material?[].concat(o.material):[])m.dispose();});
  }
});
check('fire_pits_resolve_from_their_entity_without_duplicate_marker',()=>{
  const pit={id:'pit',shape:'round',at:[5,5],radius:2,fuel:'wood',entity:'switch.fire'};
  const l={markers:[{kind:'light',device_id:'d',entity_id:'switch.fire',at:[0,0,0]}]};
  const p={buildings:[],site:{fire_pit:[pit]}};
  const out=resolveEmitters(l,{'switch.fire':{state:'on'}},p);assert.equal(out.length,1);assert.equal(out[0].on,true);
  assert.equal(resolveEmitters(l,{'switch.fire':{state:'off'}},p)[0].on,false);
  const ib=resolveEmitters({markers:[]},{'input_boolean.fire':{state:'on'}},{buildings:[],site:{fire_pit:[{...pit,entity:'input_boolean.fire'}]}});
  assert.equal(ib.length,1);assert.equal(ib[0].on,true);
  // Live opts out: the entity's own marker resolves through the legacy rules.
  const live=resolveEmitters(l,{'switch.fire':{state:'on'}},p,{firePits:false});
  assert.equal(live.length,1);assert.equal(live[0].legacy,true);assert.equal(live[0].device_id,'d');
});
check('unnamed_pits_take_their_index_like_the_yard_builder',()=>{
  const pits=[{shape:'round',at:[5,5],radius:2,fuel:'wood',entity:'switch.a'},{id:'',shape:'round',at:[15,5],radius:2,fuel:'wood',entity:'switch.b'}];
  const out=resolveEmitters({markers:[]},{},{buildings:[],site:{fire_pit:pits}});
  assert.deepEqual(out.map(e=>e.device_id).sort(),['object:fire_pit:0','object:fire_pit:1']);
});
check('signature_changes_on_aim_cone_size_facing_path',()=>{
  const rows=[fixture('s','spot',{at:[1,2,3],aim:[4,5,0],cone_deg:90,softness:.3}),fixture('a','area',{at:[1,2,3],size_ft:[2,3],facing:'up'}),fixture('l','line',{path:[[0,0,1],[10,0,1]],width_in:.5,facing:'down'})];
  const initial=emitterSignature(resolve(rows));
  for(const mutate of [r=>r[0].aim[0]++,r=>r[0].cone_deg++,r=>r[0].softness=.4,r=>r[1].size_ft[0]++,r=>r[1].facing='down',r=>r[2].path[1][0]++,r=>r[2].width_in=1,r=>r[0].share=2]) {
    const copy=structuredClone(rows);mutate(copy);assert.notEqual(emitterSignature(resolve(copy)),initial);
  }
  assert.notEqual(emitterSignature(resolve(rows,{output_lm:504})),initial);
  assert.equal(emitterSignature(resolve(rows).reverse()),initial,'canonical fixture order');
  assert.equal(emitterSignature(resolveEmitters(layout(rows),{},plan)),initial,'HA changes do not invalidate transport');
});

let passed=0;
for(const [name,fn] of checks)try{await fn();passed++;console.log('  ok   '+name);}catch(e){console.log('  FAIL '+name+' '+e.message);}
console.log(`${passed}/${checks.length} passed`);process.exit(passed===checks.length?0:1);
"""

# Reuse the neighbouring test's fake DOM/view, but execute our own cases through
# the actual live entry point and rig. No browser or source-grep assertions.
_LIVE_SPLIT = "check('lights_mode_never_requests_a_time_look_change'"
if REAL_LIGHTS_DRIVER.count(_LIVE_SPLIT) != 1:
    raise AssertionError('test_twin_real_lights_js.DRIVER changed: cannot find its first check to reuse the fake view')
LIVE_DRIVER = REAL_LIGHTS_DRIVER.split(_LIVE_SPLIT)[0] + r"""
const {layoutKey,keepLive}=await import(file('static/twin/live/live.js'));
check('live_uses_fixtures_not_markers_and_keeps_distinct_pool_slots',async()=>{
  const saved=structuredClone(layout);
  layout.light_fixtures={'light.a1':[
    {id:'fixture:one',shape:'point',ref:'absolute',at:[3,4,0]},
    {id:'fixture:two',shape:'point',ref:'absolute',at:[5,4,2]}
  ]};
  layout.light_fixtures_meta={'light.a1':{output_lm:1000}};
  const {view,live}=await mounted();
  try {
    live.setMode('lights');live.draw();
    const lights=live.lights().filter(e=>e.device==='a1');
    assert.equal(lights.length,2);assert.ok(lights.every(e=>e.real));
    assert.deepEqual(lights.map(e=>e.at),[[3,4,0],[5,4,2]]);
    assert.equal(new Set(lights.map(e=>e.fixture_id)).size,2);
    const actual=pool(view).filter(l=>l.intensity>0);
    for(const at of [[3,4,0],[5,4,2]])assert.ok(actual.some(l=>l.position.distanceTo(new THREE.Vector3(at[0]*FT,at[2]*FT,-at[1]*FT))<1e-10));
    states['light.a1'].state='off';await live.refresh();
    assert.ok(live.lights().filter(e=>e.device==='a1').every(e=>e.intensity===0&&!e.real));
  } finally {live.stop();for(const k of Object.keys(layout))delete layout[k];Object.assign(layout,saved);}
});
check('live_switch_and_paused_tv_emit_and_stale_turns_them_off',async()=>{
  const saved=structuredClone(layout);
  layout.light_fixtures={
    'switch.landscape':[{id:'fixture:switch',shape:'point',ref:'absolute',at:[8,5,1]}],
    'media_player.tv':[{id:'fixture:tv',shape:'area',ref:'absolute',at:[9,5,4],size_ft:[3,2],facing:[0,-1,0]}]
  };
  const {view,live}=await mounted();
  try{
    states['switch.landscape']={state:'on'};states['media_player.tv']={state:'paused'};await live.refresh();live.draw();
    assert.ok(live.lights().find(e=>e.device==='switch.landscape').intensity>0);
    assert.ok(live.lights().find(e=>e.device==='media_player.tv').intensity>0);
    states['media_player.tv'].state='idle';await live.refresh();
    assert.equal(live.lights().find(e=>e.device==='media_player.tv').intensity,0);
    reachable=false;await live.refresh();
    assert.ok(live.lights().every(e=>e.intensity===0));
  }finally{live.stop();for(const k of Object.keys(layout))delete layout[k];Object.assign(layout,saved);}
});
check('live_layout_key_covers_resolved_fixture_edits_without_server_signatures',()=>{
  const l={markers:[],light_fixtures:{'light.a':[{id:'fixture:s',shape:'spot',ref:'absolute',at:[1,2,3],aim:[3,4,0],cone_deg:90,softness:.3}]}};
  const initial=layoutKey(l);
  for(const mutate of [f=>f.aim[0]++,f=>f.cone_deg++,f=>f.at[2]++]){
    const c=structuredClone(l);mutate(c.light_fixtures['light.a'][0]);assert.notEqual(layoutKey(c),initial);
  }
  const c=structuredClone(l);c.light_fixtures_meta={'light.a':{output_lm:1000}};assert.notEqual(layoutKey(c),initial);
});
check('live_fire_pits_stay_object_lamps_with_flame_colour_scale_and_bake',async()=>{
  // Existing houses: a pit lights exactly as before fixtures (review I-1).
  const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-10,`${a} != ${b}`),near=(a,b)=>a.forEach((v,i)=>close(v,b[i]));
  const view=makeView('low');
  const pits=[{id:'gas',shape:'rectangle',polygon:[[0,0],[12,0],[12,2],[0,2]],fuel:'gas',entity:'switch.fire'},
    {id:'wood',shape:'round',at:[14,5],radius:2,fuel:'wood',entity:'switch.fire'},
    {id:'ib',shape:'round',at:[20,5],radius:2,fuel:'wood',entity:'input_boolean.fire'}];
  view.plan.site={fire_pit:pits};
  const {buildFirePit,fireFlameMaterial}=await import(file('static/twin/fire_pits.js'));
  const {resolveEmitters}=await import(file('static/twin/live/emitters.js'));
  const group=new THREE.Group();group.scale.setScalar(FT);view.scene.add(group);
  const fireAt={};
  for(const pit of pits) buildFirePit(group,pit,0,{id:'fire_pit:'+pit.id,mat:name=>new THREE.MeshStandardMaterial({name}),
    plain:(name,color,extra={})=>extra.fireShader?fireFlameMaterial():new THREE.MeshStandardMaterial({name,color,...extra})});
  group.traverse(o=>{for(const m of o.material?[].concat(o.material):[]){const l=m.userData?.objectLight;if(l?.fireLightAt)fireAt[l.id]=l.fireLightAt;}});
  const calls=[];view.bake={fresh:()=>['object:fire_pit:gas'],light:(id,rgb,intensity)=>calls.push({id,rgb,intensity})};
  states=initialStates();states['switch.fire']={state:'on'};states['input_boolean.fire']={state:'on'};reachable=true;
  const live=await mountLive(view,{api});
  try{
    live.setMode('lights');live.draw();
    const derived=resolveEmitters(layout,states,view.plan).filter(e=>e.fire_pit);
    assert.equal(derived.length,3,'the resolver still derives pit emitters for the bake slice');
    const actual=live.lights().filter(e=>e.device.startsWith('object:fire_pit:'));
    assert.deepEqual(actual.map(e=>e.device).sort(),['object:fire_pit:gas','object:fire_pit:ib','object:fire_pit:wood'],'one lamp per pit, no derived duplicates');
    assert.ok(!live.lights().some(e=>String(e.fixture_id||'').startsWith('fixture:fire_pit:')),'no derived emitter reaches the live pool');
    for(const row of actual){
      const id=row.device.slice('object:'.length),at=fireAt[id];assert.ok(at,'flame anchor for '+id);
      near(row.at,[at[0],-at[2],at[1]]);
      assert.deepEqual(row.rgb.map(Math.round),[255,154,60],'flame colour #ff9a3c');
      close(row.intensity,.5);
    }
    const gas=actual.find(e=>e.device==='object:fire_pit:gas');assert.equal(gas.baked,true,'fresh bake drives the pit channel');
    assert.ok(calls.some(c=>c.id==='object:fire_pit:gas'&&Math.abs(c.intensity-.5)<1e-12),'baked object:fire_pit:<id> channel lit at the flame scale');
    assert.ok(!actual.find(e=>e.device==='object:fire_pit:wood').baked);
    assert.ok(tagged(view,'bulb').filter(b=>String(b.userData.bulb).startsWith('object:fire_pit:')).every(b=>!b.visible));
    states['input_boolean.fire'].state='off';await live.refresh();
    assert.equal(live.lights().find(e=>e.device==='object:fire_pit:ib').intensity,0);
  }finally{live.stop();states=initialStates();}
});
check('live_recheck_remounts_on_fixture_aim_edit',async()=>{
  const saved=structuredClone(layout);
  layout.light_fixtures={'light.a1':[{id:'fixture:spot',shape:'spot',ref:'absolute',at:[2,2,8],aim:[2,4,0],cone_deg:90,softness:.3}]};
  const view=makeView('low'),keeper=keepLive(view,{api});
  try{
    await keeper.check();const first=keeper.live();assert.ok(first);
    await keeper.check();assert.equal(keeper.live(),first);
    layout.light_fixtures['light.a1'][0].aim[0]++;
    await keeper.check();assert.ok(keeper.live());assert.notEqual(keeper.live(),first);
  }finally{keeper.live()?.stop();keeper.stop();for(const k of Object.keys(layout))delete layout[k];Object.assign(layout,saved);}
});
let passed=0;
for(const [name,fn] of checks)try{await fn();passed++;console.log('  ok   '+name);}catch(e){console.log('  FAIL '+name+' '+e.stack);}
console.log(`${passed}/${checks.length} passed`);process.exit(passed===checks.length?0:1);
"""


def run():
    node = shutil.which('node')
    assert node, 'Node is required'
    paths = []
    try:
        for suffix, content in (('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix()})), ('.mjs', LIVE_DRIVER)):
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, delete=False) as stream:
                paths.append(Path(stream.name))
                stream.write(content)
        failed = False
        for driver in (paths[0], paths[2]):
            result = subprocess.run([node, str(driver), str(paths[1])], capture_output=True,
                                    text=True, encoding='utf-8', timeout=120)
            print(result.stdout, end='')
            if result.returncode:
                print(result.stderr[-3000:], end='')
                failed = True
        return int(failed)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(1 if run() else 0)
