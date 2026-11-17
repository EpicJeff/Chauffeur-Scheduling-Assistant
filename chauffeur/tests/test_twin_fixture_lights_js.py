"""Typed live fixture pool; execute the real resolver and mounted live layer in Node.

GPU program-key and sampler proofs live in test_twin_shadowmask_live.py.
"""
import sys
from test_twin_real_lights_js import DRIVER as BASE, run
import test_twin_real_lights_js as harness

DRIVER = BASE[:BASE.index("check('lights_mode_never")] + r"""
const {resolveEmitters} = await import(file('static/twin/live/emitters.js'));
const close = (a,b) => assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
const f = (id,shape,more={}) => ({id:'fixture:'+id,shape,ref:'absolute',at:[2,2,3],...more});
const fixtures = rows => ({markers:[],light_fixtures:{'light.test':rows}});
const reading = {'light.test':{state:'on',attributes:{brightness:128,rgb_color:[255,80,20]}}};
const emitted = rows => resolveEmitters(fixtures(rows),reading,{buildings:[],site:{}});
const typed = scene => {
  const rows={point:[],spot:[],area:[]};
  scene.traverse(o=>{if(o.isPointLight)rows.point.push(o);if(o.isSpotLight)rows.spot.push(o);if(o.isRectAreaLight)rows.area.push(o);});return rows;
};
const candidates = rows => emitted(rows).map(e=>({device:e.fixture_id,emitter:e,at:e.at||e.path[0],position:new THREE.Vector3(...e.position),distance:e.range*FT,intensity:e.brightness,rgb:e.rgb}));
check('quota_respected_per_type_and_tier',()=>{
  for(const [tier,quota] of Object.entries({low:[4,1,2,0],medium:[8,2,4,1],high:[12,4,8,1],max:[16,6,12,1]})){
    const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier});rig.show(true);
    const input=candidates(Array.from({length:20},(_,i)=>f('p'+i,'point',{at:[i,0,3]})).concat(
      Array.from({length:10},(_,i)=>f('s'+i,'spot',{at:[i,0,3],aim:[i,0,0]})),
      Array.from({length:20},(_,i)=>f('a'+i,'area',{at:[i,0,3],size_ft:[2,1],facing:'down'}))));
    rig.update(input,[0,0,0]);const pools=typed(scene);
    for(const [index,type] of ['point','spot','area'].entries()){
      assert.equal(pools[type].length,quota[index],tier+' '+type);assert.equal(pools[type].filter(l=>l.intensity>0).length,quota[index]);
    }
    assert.equal([...pools.point,...pools.spot].filter(l=>l.castShadow&&l.intensity>0).length,quota[3]);
    assert.ok(pools.area.every(l=>!l.castShadow));rig.stop();assert.equal(scene.children.length,0);
  }
  const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier:'low'});rig.show(true);
  const line=candidates([f('rope','line',{path:[[0,0,4],[60,0,4]],width_in:.5,facing:'down'})]);
  const selected=rig.update(line,[0,0,0]);const pool=typed(scene).area;
  assert.equal(pool.filter(l=>l.intensity>0).length,2);assert.ok(selected.has('fixture:rope'));
  for(const light of pool){close(light.width,15*FT);close(light.height,.5/12*FT);close(light.intensity,line[0].emitter.luminance);}
  assert.equal(rig.overflow(),true,'two of four pieces are glow only');rig.stop();
});
check('closest_caster_across_types_and_warm_variants',()=>{
  const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier:'high'});rig.show(true);
  const input=candidates([f('near','spot',{at:[1,0,3],aim:[1,0,0]}),f('far','point',{at:[10,0,3]})]);
  rig.update(input,[0,0,0]);let pools=typed(scene);
  assert.ok(pools.spot[0].castShadow);assert.ok(pools.point.every(l=>!l.castShadow));
  const variants=[];rig.warm(()=>variants.push(pools.spot.some(l=>l.castShadow)?'spot':'point'));
  assert.deepEqual(variants,['point','spot']);assert.ok(pools.spot[0].castShadow,'warm restores the caster variant');
  const identities=Object.values(pools).flat().map(l=>l.uuid);
  rig.update(input,[10,0,0]);assert.ok(pools.point[0].castShadow);assert.ok(pools.spot.every(l=>!l.castShadow));
  rig.update([], [0,0,0]);assert.equal(Object.values(pools).flat().filter(l=>l.castShadow).length,1);
  assert.deepEqual(Object.values(typed(scene)).flat().map(l=>l.uuid),identities);rig.stop();
});
check('spot_targets_aim_with_cone_and_penumbra',()=>{
  const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier:'low'});rig.show(true);
  const input=candidates([f('beam','spot',{at:[2,4,6],aim:[8,10,0],cone_deg:60,softness:.7})]);
  rig.update(input,[0,0,0]);const spot=typed(scene).spot[0];
  close(spot.angle,Math.PI/6);close(spot.penumbra,.7);close(spot.intensity,input[0].emitter.cd);
  assert.deepEqual(spot.target.position.toArray(),[8*FT,0,-10*FT]);assert.equal(spot.target.parent,scene);
  assert.deepEqual(spot.position.toArray(),input[0].emitter.position);
  rig.update(candidates([f('narrow','spot',{aim:[8,10,0],cone_deg:10,share:.1}),f('wide','spot',{aim:[8,10,0],cone_deg:90,share:.9})]),[0,0,0]);
  close(spot.angle,Math.PI/4,'at the same distance prefer output, independently of beam concentration');
  rig.stop();assert.equal(scene.children.length,0);
});
check('area_orientation_dimensions_output_and_line_centres',()=>{
  const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier:'low'});rig.show(true);
  const input=candidates([f('panel','area',{at:[2,4,6],size_ft:[4,2],facing:'up',rotation_deg:30})]);
  rig.update(input,[0,0,0]);const area=typed(scene).area.find(l=>l.intensity>0);
  close(area.width,4*FT);close(area.height,2*FT);close(area.intensity,input[0].emitter.luminance);
  const normal=new THREE.Vector3(0,0,-1).applyQuaternion(area.quaternion),width=new THREE.Vector3(1,0,0).applyQuaternion(area.quaternion);
  assert.ok(normal.distanceTo(new THREE.Vector3(0,1,0))<1e-8);
  assert.ok(width.distanceTo(new THREE.Vector3(Math.cos(Math.PI/6),0,-.5))<1e-8);
  assert.deepEqual(area.position.toArray(),[2*FT,6*FT,-4*FT]);
  const line=candidates([f('run','line',{path:[[0,0,6],[60,0,6]],width_in:.5,facing:'down'})]);
  rig.update(line,[0,0,0]);const lights=typed(scene).area;
  close(lights[0].position.x,7.5*FT);close(lights[1].position.x,22.5*FT);
  for(const l of lights){close(l.position.y,(6-2/12)*FT);assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(l.quaternion).distanceTo(new THREE.Vector3(0,-1,0))<1e-8);}
  rig.stop();
});
check('bent_line_pieces_face_out_on_every_leg',async()=>{
  const {linePieces,fixtureRotation}=await import(file('static/twin/live/fixture_glow.js'));
  for(const facing of ['out','in','down','up']){
    const e=emitted([f('bend','line',{path:[[0,0,4],[8,0,4],[8,8,4]],width_in:.5,facing})])[0];
    const pieces=linePieces(e);assert.equal(pieces.length,4);
    pieces.forEach((piece,i)=>{
      const direction=i<2?new THREE.Vector3(1,0,0):new THREE.Vector3(0,0,-1);
      const width=new THREE.Vector3(1,0,0).applyQuaternion(piece.rotation);
      const normal=new THREE.Vector3(0,0,-1).applyQuaternion(piece.rotation);
      assert.ok(Math.abs(width.y)<1e-6,`${facing} leg ${i}: width stays horizontal`);
      assert.ok(width.distanceTo(direction)<1e-6,`${facing} leg ${i}: width follows its leg`);
      const right=new THREE.Vector3(-direction.z,0,direction.x);
      const expected=facing==='out'?right:facing==='in'?right.negate():new THREE.Vector3(0,facing==='up'?1:-1,0);
      assert.ok(normal.distanceTo(expected)<1e-6,`${facing} leg ${i}: emitting normal follows its leg`);
      assert.ok(Math.abs(normal.dot(direction))<1e-6);
    });
    const straight=emitted([f('straight','line',{path:[[0,0,4],[16,0,4]],width_in:.5,facing})])[0];
    const original=fixtureRotation(straight);
    for(const piece of linePieces(straight))assert.ok(piece.rotation.angleTo(original)<1e-6,'straight-line frame is unchanged');
  }
});
check('legacy_over_quota_is_not_authored_overflow',()=>{
  const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier:'low'});
  const legacy=Array.from({length:6},(_,i)=>({device:'legacy:'+i,at:[i,0,3],position:new THREE.Vector3(i*FT,3*FT,0),distance:10*FT,intensity:1,rgb:[255,255,255],
    ...(i%2?{emitter:{legacy:true,shape:'point'}}:{})}));
  const authored=candidates([f('panel','area',{size_ft:[2,1],facing:'down'})]);
  try{
    const selected=rig.update([...legacy,...authored],[0,0,0]);
    assert.equal(selected.size,5);assert.ok(selected.has('fixture:panel'));
    assert.equal(rig.overflow(),false,'legacy lamps keep the floor wash');
    const distant=candidates([f('distant','point',{at:[100,0,3]})]);
    rig.update([...legacy,...authored,...distant],[0,0,0]);
    assert.equal(rig.overflow(),true,'a legacy slot can still displace an authored light');
  }finally{rig.stop();}
});
check('glow_strip_follows_path_and_state',async()=>{
  const {createFixtureGlow}=await import(file('static/twin/live/fixture_glow.js'));
  const scene=new THREE.Scene(),rows=emitted([f('rope','line',{path:[[0,0,4],[3,0,4],[3,5,4]],width_in:1}),f('screen','area',{size_ft:[4,2],facing:[0,1,0],rotation_deg:20})]);
  const glow=createFixtureGlow(scene,rows[0]);glow.update(rows[0].rgb,rows[0].brightness,true);
  const mesh=scene.children[0];assert.ok(mesh.isMesh);assert.equal(mesh.material.toneMapped,false);assert.equal(mesh.material.lights,undefined);
  mesh.geometry.computeBoundingBox();const box=mesh.geometry.boundingBox;
  for(const [a,b] of [[box.min.x,0],[box.max.x,3*FT+FT/24],[box.min.z,-5*FT],[box.max.z,FT/24],[box.min.y,(4-2/12)*FT-FT/24],[box.max.y,(4-2/12)*FT+FT/24]])assert.ok(Math.abs(a-b)<1e-6);
  const second=createFixtureGlow(scene,rows[0]);second.update(rows[0].rgb,rows[0].brightness,true);
  assert.equal(scene.children[1].material,mesh.material,'one material per colour bucket');
  glow.update(rows[0].rgb,0,true);assert.equal(mesh.visible,false);assert.equal(scene.children[1].visible,true);
  const panel=createFixtureGlow(scene,rows[1]);panel.update(rows[1].rgb,1,true);assert.equal(scene.children[2].geometry.parameters.width,4*FT);
  const plain=scene.children[2].material.color.clone();
  const hot=createFixtureGlow(scene,rows[1],3);hot.update(rows[1].rgb,1,true);
  assert.notEqual(scene.children[3].material,scene.children[2].material);
  plain.toArray().forEach((v,i)=>assert.ok(Math.abs(scene.children[3].material.color.toArray()[i]-3*v)<.02));
  assert.ok(Math.max(...scene.children[3].material.color.toArray())>1,'a glowing view draws the strip above white');
  hot.stop();
  glow.stop();second.stop();panel.stop();assert.equal(scene.children.length,0);
});
check('mounted_shapes_state_overflow_and_cleanup',async()=>{
  layout.light_fixtures={'light.a1':[f('rope','line',{path:[[0,0,6],[60,0,6]],facing:'down',width_in:.5}),f('beam','spot',{aim:[4,4,0],cone_deg:50,softness:.2}),f('beam2','spot',{at:[10,2,3],aim:[12,4,0]})]};
  const {view,live}=await mounted('low');
  try{
    live.setMode('lights');const pools=typed(view.scene);assert.equal(pools.spot.filter(l=>l.intensity>0).length,1);assert.equal(pools.area.filter(l=>l.intensity>0).length,2);
    const glows=()=>view.scene.children.filter(o=>o.userData.fixtureGlow);assert.equal(glows().length,1);assert.ok(glows()[0].visible);
    assert.ok(!washShown(view,'A'),'authored overflow is glow only, without the legacy room wash');
    assert.ok(document.getElementById('twin-mode-legend').textContent.includes('Some lights are shown as glow only on this tier'));
    states['light.a1'].state='off';await live.refresh();assert.ok(!glows()[0].visible);assert.ok(pools.spot.every(l=>l.intensity===0));
    states['light.a1'].state='on';await live.refresh();assert.ok(glows()[0].visible);
    reachable=false;await live.refresh();assert.ok(!glows()[0].visible);
    reachable=true;await live.refresh();live.setMode('climate');assert.ok(!glows()[0].visible);assert.ok([...pools.point,...pools.spot,...pools.area].every(l=>!l.visible));
  }finally{live.stop();delete layout.light_fixtures;delete layout.light_fixtures_meta;reachable=true;}
  assert.ok(!view.scene.children.some(o=>o.userData.fixtureGlow||o.isLight));
});
check('zero_output_has_no_live_light_or_glow',async()=>{
  layout.light_fixtures={'light.a1':[f('zero','area',{size_ft:[2,1],facing:'up'})]};
  layout.light_fixtures_meta={'light.a1':{output_lm:0}};
  const {view,live}=await mounted('low');
  try{
    live.setMode('lights');assert.ok(typed(view.scene).area.every(l=>l.intensity===0));
    assert.ok(view.scene.children.filter(o=>o.userData.fixtureGlow).every(o=>!o.visible));
    assert.equal(live.lights().find(l=>l.fixture_id==='fixture:zero').intensity,0);
  }finally{live.stop();delete layout.light_fixtures;delete layout.light_fixtures_meta;}
});
check('legacy_point_pool_unchanged',async()=>{
  for(const [tier,count,shadows] of [['low',4,0],['medium',8,0],['high',16,2],['max',16,2]]){
    const scene=new THREE.Scene(),rig=R.createRealLights({scene,tier},{fixtures:false}),pools=typed(scene);
    assert.equal(pools.point.length,count);assert.equal(pools.point.filter(l=>l.castShadow).length,shadows);
    assert.equal(pools.spot.length,0);assert.equal(pools.area.length,0);rig.stop();
  }
  const {view,live}=await mounted('low');try{
    live.setMode('lights');const points=typed(view.scene).point;assert.equal(points.length,4);
    assert.deepEqual(realSet(live),['a1','a2','a3','a4']);
    for(const id of realSet(live)){const light=lampAt(view,id);assert.ok(light,id);close(light.intensity,row(live,id).intensity*40);}
    assert.equal(typed(view.scene).spot.length,0);assert.equal(typed(view.scene).area.length,0);
  }finally{live.stop();}
});
check('pit_only_house_keeps_legacy_profile_at_every_tier',async()=>{
  for(const tier of ['low','medium','high','max']) {
    const baseline=makeView(tier),a=await mountLive(baseline,{api});
    const profile=v=>Object.values(typed(v.scene)).map(pool=>[pool.length,pool.filter(l=>l.castShadow).length]);
    const expected=profile(baseline);a.stop();
    const view=makeView(tier);view.plan.site={fire_pit:[{id:'pit',at:[8,5],radius:2,fuel:'gas',entity:'switch.fire'}]};
    states['switch.fire']={state:'on'};
    const live=await mountLive(view,{api});
    try {
      assert.deepEqual(profile(view),expected,tier);
      assert.ok(live.lights().find(l=>l.device==='object:fire_pit:pit').intensity>0,'pit still resolves and emits');
    } finally {live.stop();delete states['switch.fire'];}
  }
});
""" + BASE[BASE.index('let passed = 0;'):]

if __name__ == '__main__':
    harness.DRIVER = DRIVER
    sys.exit(1 if run() else 0)
