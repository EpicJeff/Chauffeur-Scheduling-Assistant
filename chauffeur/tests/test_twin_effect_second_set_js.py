"""Second-set geometry, sizing and water response through production entry points."""
import sys
import test_twin_effect_visuals_js as harness
from test_twin_untouched_house_js import COMMON

harness.DRIVER = COMMON + r"""
const {buildEffects}=await import(file('static/twin/effects/index.js'));
const W=await import(file('static/twin/effects/water_ripples.js'));
const {inPolygon}=await import(file('static/twin/twin_ground.js'));
const Y=await import(file('static/twin/twin_yard.js'));
const E=await import(file('static/twin/live/emitters.js'));
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
const kinds=['spa_jet','steam','sheer','deck_jet','mist'];
const f=(type,more={})=>({id:'effect:'+type,type,shape:type==='sheer'?'line':'point',ref:'absolute',
 ...(type==='sheer'?{path:[[2,1,4],[8,1,4]],facing:'in'}:{at:[1,5,-.7]}),...more});
const plan=(...effects)=>({buildings:[],site:{lot:square(-20,-20,80),pool:{id:'pool',polygon:square(0,0,20),depth:4,
 features:[{id:'spa',kind:'spa',polygon:square(12,12,6),mode:'raised',raise_in:12}]}},effect_fixtures:effects});
const effectMeshes=group=>{const out=[];group.traverse(o=>{if(o.isMesh)out.push(o);});return out;};
for(const type of kinds)await test(type+'_builds_one_unlit_mesh_and_freezes_at_sized_pose',()=>{
 for(const tier of ['low','medium','high']){
  const fixture=f(type,{entity:'switch.effect',sensor:'sensor.size',sensor_min:0,sensor_max:100,size_min:.5,size_max:5});
  const fx=buildEffects(plan(fixture),{tier}),rows=effectMeshes(fx.group);assert.equal(rows.length,1);
  const mesh=rows[0],geometry=mesh.geometry.uuid;
  assert.ok(mesh.material.isShaderMaterial);assert.equal('transmission' in mesh.material,false);
  assert.equal(mesh.material.depthWrite,false);assert.equal(mesh.material.side,THREE.DoubleSide);
  assert.equal(mesh.geometry.userData.bakeExcluded,true);assert.equal(mesh.userData.effectFixture,true);
  assert.equal(mesh.castShadow,false);assert.equal(mesh.receiveShadow,false);
  for(const [value,size] of [[0,.5],[100,5]]){
   const states={'switch.effect':{state:'on'},'sensor.size':{state:value}};
   fx.update(states,false,10+value);fx.update(states,false,12+value,.19);
   close(fx.fixtures[0].size,size);assert.equal(mesh.material.uniforms.light.value,.19);
   assert.equal(mesh.material.uniforms.time.value,tier==='low'?0:12+value);
   assert.equal(mesh.geometry.uuid,geometry);
   assert.ok([...mesh.geometry.attributes.position.array].every(Number.isFinite));
  }
 }
});
await test('spa_jet_off_water_draws_nothing_and_coping_aims_to_water',()=>{
 const dry=buildEffects(plan(f('spa_jet',{at:[50,50,0]})),{editor:true});assert.equal(effectMeshes(dry.group).length,0);
 const p=plan(f('spa_jet',{at:[-2,5,0],size_min:3,size_max:3})),fx=buildEffects(p,{editor:true}),row=fx.fixtures[0];
 assert.equal(row.built.aim.body.id,'pool');assert.ok(row.built.aim.normal[0]>0);
 const bounds=new THREE.Box3().setFromObject(fx.group);assert.ok(bounds.min.y<-.4);assert.ok(bounds.max.y<0);
 assert.equal(W.rippleSources(plan(f('spa_jet',{at:[50,50,0]}))).length,0);
 const coping=buildEffects(plan(f('spa_jet',{at:[11.8,15,1]})),{editor:true});
 assert.equal(coping.fixtures[0].built.aim.body.id,'spa');assert.equal(W.rippleSources(plan(f('spa_jet',{at:[11.8,15,1]})))[0].id,'spa');
});
await test('steam_covers_its_body_and_dry_steam_is_three_feet_across',()=>{
 const fx=buildEffects(plan(f('steam',{at:[14,14,0],size_min:4,size_max:4})),{editor:true});
 assert.equal(fx.fixtures[0].built.body.id,'spa');const bounds=new THREE.Box3().setFromObject(fx.group);
 assert.ok(bounds.min.x<13&&bounds.max.x>17);assert.ok(bounds.min.z<-17&&bounds.max.z>-13);
 close(bounds.max.y-bounds.min.y,4);close(bounds.min.y,fx.fixtures[0].built.body.height+.025);
 const dry=buildEffects(plan(f('steam',{at:[50,50,2],size_min:2,size_max:2})),{editor:true});
 const box=new THREE.Box3().setFromObject(dry.group);close(box.max.x-box.min.x,3);close(box.max.y-box.min.y,2);assert.equal(dry.fixtures[0].built.body,undefined);
});
await test('pool_steam_stays_off_a_spa_inside_the_pool',()=>{
 const fx=buildEffects(plan(f('steam',{at:[5,5,0],size_min:4,size_max:4})),{editor:true});
 assert.equal(fx.fixtures[0].built.body.id,'pool');
 const p=effectMeshes(fx.group)[0].geometry.attributes.position;let over=0;
 for(let i=0;i<p.count;i++)if(p.getX(i)>12&&p.getX(i)<18&&-p.getZ(i)>12&&-p.getZ(i)<18)over++;
 assert.ok(p.count>0);assert.equal(over,0,'no wisp stands over the spa');
 const bounds=new THREE.Box3().setFromObject(fx.group);
 assert.ok(bounds.min.x<3&&bounds.max.x>17&&bounds.min.z<-17&&bounds.max.z>-3,'the rest of the pool still steams');
 // The same pool with no spa steams all over.
 const bare=plan(f('steam',{at:[5,5,0],size_min:4,size_max:4}));bare.site.pool.features=[];
 const q=effectMeshes(buildEffects(bare,{editor:true}).group)[0].geometry.attributes.position;
 assert.ok(q.count>p.count);
});
await test('mist_point_and_line_drop_the_authored_distance',()=>{
 for(const shape of ['point','line']){
  const fixture=f('mist',{shape,at:undefined,...(shape==='line'?{path:[[1,1,8],[12,1,8]]}:{at:[1,1,8]}),size_min:6,size_max:6});
  const fx=buildEffects(plan(fixture),{editor:true}),box=new THREE.Box3().setFromObject(fx.group);
  const top=shape==='line'?fx.fixtures[0].path[0][2]:8;
  close(box.min.y,top-6);close(box.max.y,top);assert.equal(effectMeshes(fx.group).length,1);
  if(shape==='line')assert.ok(box.max.x-box.min.x>10);
 }
});
await test('sheer_lands_at_throw_and_respects_automatic_and_manual_drop',()=>{
 for(const drop of [undefined,2]){
  const fixture=f('sheer',{size_min:3,size_max:3,...(drop?{drop_ft:drop}:{})}),fx=buildEffects(plan(fixture),{editor:true});
  const row=fx.fixtures[0],p=effectMeshes(fx.group)[0].geometry.attributes.position,part=effectMeshes(fx.group)[0].geometry.attributes.part,uv=effectMeshes(fx.group)[0].geometry.attributes.uv;
  let checked=0;
  for(let i=0;i<p.count;i++)if(part.getX(i)===0&&uv.getY(i)===1){
   const world=[p.getX(i)+row.path[0][0],-p.getZ(i)+row.path[0][1],p.getY(i)+row.path[0][2]];
   close(world[1],4);close(world[2],drop?2:-.37);checked++;
  }
  assert.equal(checked,2);
 }
});
await test('deck_jet_clamps_landings_inside_water_and_dry_jet_aims_at_lot_centre',()=>{
 for(const at of [[-10,10,0],[5,5,0],[22,22,0]]){
  const p=plan(f('deck_jet',{at})),fx=buildEffects(p,{editor:true}),aim=fx.fixtures[0].built.aim;
  assert.ok(aim.body);
  for(const size of [0,.1,2,8,30]){const landing=W.waterReach(aim,size);assert.ok(inPolygon(aim.body.polygon,...landing));close(landing[2],aim.body.height);}
 }
 const p=plan(f('deck_jet',{at:[50,50,2],size_min:8,size_max:8})),fx=buildEffects(p,{editor:true}),aim=fx.fixtures[0].built.aim;
 assert.equal(aim.body,undefined);assert.ok(aim.normal.every(n=>n<0));const box=new THREE.Box3().setFromObject(fx.group);assert.ok(box.min.y<.03);assert.ok(box.max.y>2);
});
await test('new_wet_effects_register_moving_sources_but_vapour_never_does',async()=>{
 for(const type of ['spa_jet','deck_jet','sheer']){
  const fixture=f(type,{sensor:'sensor.size',entity:'switch.water',sensor_min:0,sensor_max:1,size_min:2,size_max:6});
  const p=plan(fixture),fx=buildEffects(p,{tier:'low'}),yard=await Y.buildYard(p,kit(),'low'),r=yard.group.userData.ripples;
  assert.ok(r,type);assert.equal(r.rows.length,1);const row=r.rows[0],source=row.body.sources[0];let previous;
  for(const value of [0,1]){
   fx.update({'sensor.size':{state:value},'switch.water':{state:'on'}},false,10+value);r.update(fx.fixtures,10+value);
   const line=row.uniforms.rippleLines.value[0];assert.equal(row.uniforms.rippleTime.value,0);assert.ok(row.uniforms.rippleStrength.value[0]>0);
   if(source.aim){const landing=W.waterReach(source.aim,fx.fixtures[0].size);close(line.x,landing[0]);close(line.y,landing[1]);}
   if(previous)assert.notDeepEqual(line.toArray(),previous);previous=line.toArray();
  }
 }
 const dry=plan(f('steam'),f('mist'));assert.equal(W.rippleSources(dry).length,0);
 const yard=await Y.buildYard(dry,kit(),'high');assert.equal(yard.group.userData.ripples,undefined);
});
await test('new_sources_still_cap_at_eight_and_wrong_drop_never_ripples',()=>{
 const p=plan(...Array.from({length:12},(_,i)=>f('spa_jet',{id:'jet'+i,at:[1,i+1,-.5]})));
 assert.equal(W.rippleSources(p)[0].sources.length,8);
 assert.equal(W.rippleSources(plan(f('sheer',{drop_ft:2}))).length,0);
 const body={id:'concave',height:0,polygon:[[0,0],[10,0],[10,3],[3,3],[3,10],[0,10]]};
 const aim=W.waterAim({},[-1,5,0],12,[body]);for(const size of [0,2,8,30])assert.ok(inPolygon(body.polygon,...W.waterReach(aim,size)));
});
await test('sheer_leaves_dry_water_untouched_and_clips_partial_landing_to_water',async()=>{
 const away=f('sheer',{path:[[2,-1,4],[8,-1,4]],facing:'out'}),p=plan(away);
 assert.equal(W.rippleSources(p).length,0);assert.equal((await Y.buildYard(p,kit(),'low')).group.userData.ripples,undefined);
 const partial=f('sheer',{path:[[-5,1,4],[5,1,4]],facing:'in',size_min:3,size_max:3});
 const fx=buildEffects(plan(partial),{editor:true}),body=W.rippleSources(plan(partial))[0];
 const uniforms={rippleTime:{value:0},rippleLines:{value:Array.from({length:8},()=>new THREE.Vector4())},rippleStrength:{value:Array(8).fill(0)}};
 W.updateRipples([{body,uniforms}],fx.fixtures,1,'low');const line=uniforms.rippleLines.value[0];
 close(line.x,0);close(line.y,4);close(line.z,5);close(line.w,4);assert.ok(uniforms.rippleStrength.value[0]>0);
});
await test('all_new_types_cast_no_light',()=>{
 const p=plan(...kinds.map(type=>f(type)));
 assert.deepEqual(E.resolveEmitters({markers:[],devices:[],rooms:[]},{},p),[]);
});
finish();
"""

if __name__ == '__main__':
    sys.exit(harness.run())
