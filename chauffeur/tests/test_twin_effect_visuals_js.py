"""Execute real Three.js effect geometry, scene integration and bake exclusions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from test_twin_untouched_house_js import COMMON

ROOT = Path(__file__).resolve().parents[1]
DRIVER = COMMON + r"""
const {buildEffects}=await import(file('static/twin/effects/index.js'));
const {occluders}=await import(file('static/twin/bake/bake_pass.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
const basic=(type,more={})=>({id:'effect:'+type,type,shape:type==='waterfall'?'line':'point',ref:'absolute',
 ...(type==='waterfall'?{path:[[10,10,4],[20,10,4]],facing:'out'}:{at:[10,10,0]}),...more});
const planWith=(...effects)=>({buildings:[],site:{lot:square(0,0,100)},effect_fixtures:effects});
const effectMeshes=group=>{const rows=[];group.traverse(o=>{if(o.isMesh)rows.push(o);});return rows;};
const uniforms=group=>effectMeshes(group).map(mesh=>mesh.material.uniforms);
for(const type of ['waterfall','fountain','bubbler','fire'])await test(type+'_builds_two_or_fewer_procedural_meshes',async()=>{
 const out=buildEffects(planWith(basic(type)),{editor:true}),rows=effectMeshes(out.group);
 assert.equal(out.fixtures.length,1);assert.ok(rows.length>0&&rows.length<=2);
 for(const mesh of rows){assert.equal(mesh.castShadow,false);assert.equal(mesh.receiveShadow,false);assert.equal(mesh.userData.effectFixture,true);
 assert.equal(mesh.geometry.userData.bakeExcluded,true);assert.equal('transmission' in mesh.material,false);
 assert.ok(mesh.geometry.attributes.position.count>=4);assert.ok(mesh.material.isShaderMaterial);assert.ok(mesh.material.uniforms.time);
 assert.equal(mesh.material.map,undefined);
 }
 if(type!=='fire')assert.equal(rows[0].material.side,THREE.DoubleSide);
});
for(const type of ['fountain','bubbler','fire'])await test(type+'_bounding_height_tracks_real_feet',async()=>{
 for(const size of [.5,2,5]){const out=buildEffects(planWith(basic(type,{size_min:size,size_max:size})),{editor:true});
  const bounds=new THREE.Box3().setFromObject(out.group);close(bounds.min.y,0);close(bounds.max.y,size);
  assert.equal(out.fixtures[0].size,size);
 }
});
await test('bubbler_is_a_narrow_column_over_a_wide_foam_apron',async()=>{
 for(const size of [.3,1,1.5]){const out=buildEffects(planWith(basic('bubbler',{size_min:size,size_max:size})),{editor:true});
  const [body,apron]=effectMeshes(out.group),box=mesh=>new THREE.Box3().setFromObject(mesh).getSize(new THREE.Vector3());
  const column=box(body),foam=box(apron);close(column.y,size);
  // Measured above the flared foot, the column is far taller than wide once it has any height.
  if(size>=1)assert.ok(column.x<size*.5,`column ${column.x} wide for ${size} tall`);
  assert.ok(foam.x>column.x*2.5,'foam spreads well past the foot');assert.ok(foam.y<.001);
  assert.equal(body.material.uniforms.kind.value,1);assert.equal(apron.material.uniforms.kind.value,4);
 }
});
await test('bubbler_grows_taller_not_wider_with_flow',async()=>{
 const column=size=>{const out=buildEffects(planWith(basic('bubbler',{size_min:size,size_max:size})),{editor:true});
  return new THREE.Box3().setFromObject(effectMeshes(out.group)[0]).getSize(new THREE.Vector3());};
 const low=column(.5),high=column(2);close(high.y/low.y,4);
 assert.ok(high.x>low.x,'a little wider');assert.ok(high.x/low.x<1.5,`width grew ${high.x/low.x} times`);
});
await test('line_fire_spans_entire_path_with_two_draws',async()=>{
 const f=basic('fire',{shape:'line',at:undefined,path:[[10,10,2],[20,10,2],[20,20,2]],facing:'out',size_min:2,size_max:2});
 const out=buildEffects(planWith(f),{editor:true}),bounds=new THREE.Box3().setFromObject(out.group);
 assert.equal(effectMeshes(out.group).length,2);assert.ok(bounds.max.x>19);assert.ok(bounds.min.x<11);assert.ok(bounds.min.z<-19);
 close(bounds.min.y,2);close(bounds.max.y,4);assert.deepEqual(out.fixtures[0].path,f.path);
});
await test('sloped_fire_keeps_per_flame_supports_when_height_changes',async()=>{
 const f=basic('fire',{shape:'line',at:undefined,path:[[10,10,2],[20,10,4]],facing:'out',sensor:'sensor.height',sensor_min:0,sensor_max:1,size_min:1,size_max:3});
 const out=buildEffects(planWith(f),{tier:'low'}),rows=effectMeshes(out.group);
 const ids=rows.map(mesh=>mesh.geometry.uuid);
 for(const value of [0,1]){out.update({'sensor.height':{state:value}},false,value+1);
  for(const mesh of rows){const p=mesh.geometry.attributes.position,anchor=mesh.geometry.attributes.effectAnchor,uv=mesh.geometry.attributes.uv;
   assert.ok(anchor,'each flame carries its support independently of the flame height');
   close(mesh.material.uniforms.height.value,out.fixtures[0].size);close(mesh.scale.y,out.fixtures[0].size);
   for(let i=0;i<p.count;i++){
    close(anchor.getY(i)+2,(anchor.getX(i))/5+2);
    const flameHeight=(p.getY(i)-anchor.getY(i))*mesh.scale.y;
    close(flameHeight,uv.getY(i)*out.fixtures[0].size);
   }
  }
 }
 assert.deepEqual(rows.map(mesh=>mesh.geometry.uuid),ids);
});
await test('waterfall_manual_drop_and_flow_keep_geometry_stable',async()=>{
 const f=basic('waterfall',{drop_ft:3,sensor:'sensor.flow',sensor_min:0,sensor_max:100});
 const out=buildEffects(planWith(f),{tier:'low'}),rows=effectMeshes(out.group),ids=rows.map(mesh=>[mesh.uuid,mesh.geometry.uuid]);
 out.update({'sensor.flow':{state:'20'}},false,2);const small=rows[0].material.uniforms.flow.value;
 const bounds=new THREE.Box3().setFromObject(out.group);close(bounds.max.y,4);close(bounds.min.y,1);
 out.update({'sensor.flow':{state:'100'}},false,3);assert.ok(rows[0].material.uniforms.flow.value>small);
 assert.deepEqual(rows.map(mesh=>[mesh.uuid,mesh.geometry.uuid]),ids);
 assert.equal(rows[0].material.uniforms.strength.value,1);
});
await test('waterfall_automatic_landing_uses_ground_pool_and_spa',async()=>{
 const f=basic('waterfall');
 const ground=buildEffects(planWith(f),{editor:true});close(new THREE.Box3().setFromObject(ground.group).min.y,0);
 const poolPlan=planWith(f);poolPlan.site.pool={polygon:square(8,8,20),elevation:1,depth:4,features:[]};
 const pool=buildEffects(poolPlan,{editor:true});close(new THREE.Box3().setFromObject(pool.group).min.y,.63);
 poolPlan.site.pool.features=[{id:'spa',kind:'spa',polygon:square(8,8,20),mode:'raised',raise_in:12,depth_in:36}];
 const spa=buildEffects(poolPlan,{editor:true});close(new THREE.Box3().setFromObject(spa.group).min.y,1-.12+.45+1-2/12);
});
await test('all_non_low_tiers_advance_time_while_low_stays_fixed',async()=>{
 for(const tier of ['low','medium','high'])for(const type of ['waterfall','fountain','bubbler','fire']){
  const out=buildEffects(planWith(basic(type)),{tier});out.update({},false,2);const before=uniforms(out.group).map(u=>u.time.value);
  out.update({},false,3);const after=uniforms(out.group).map(u=>u.time.value);
  assert.ok(after.every((value,i)=>tier==='low'?value===before[i]:value>before[i]),tier+' '+type);
 }
});
await test('water_takes_the_scene_light_level_and_fire_keeps_its_own',async()=>{
 for(const type of ['waterfall','fountain','bubbler']){
  const out=buildEffects(planWith(basic(type)));assert.ok(uniforms(out.group).every(u=>u.light.value===1),type);
  out.update({},false,1,.18);assert.ok(uniforms(out.group).every(u=>u.light.value===.18),type);
 }
 const fire=buildEffects(planWith(basic('fire')));fire.update({},false,1,.18);
 assert.ok(uniforms(fire.group).every(u=>u.light===undefined));
});
await test('editor_preview_ignores_links_and_runs_authored_strength',async()=>{
 const f=basic('fountain',{entity:'switch.pump',sensor:'sensor.rpm',sensor_min:1000,sensor_max:3450,strength:.25});
 const out=buildEffects(planWith(f),{editor:true});out.update({},true,2);
 const row=out.fixtures[0];assert.equal(row.active,true);assert.equal(row.t,.25);assert.equal(row.size,2.25);assert.equal(row.opacity,1);assert.equal(row.group.visible,true);
});
await test('floor_reference_level_and_numeric_strength_are_independent',async()=>{
 const f=basic('fountain',{ref:'floor',building:'a',level:'L2',at:[10,10,1],strength:.25});
 const p=planWith(f);p.buildings=[{id:'a',base:0,position:[0,0],levels:[{id:'L2',elevation:8,ceiling:8}]}];
 const out=buildEffects(p,{editor:true}),row=out.fixtures[0];assert.deepEqual(row.position,[10,10,9]);
 assert.equal(row.t,.25);assert.equal(row.size,2.25);close(new THREE.Box3().setFromObject(out.group).max.y,11.25);
});
await test('runtime_exposes_eased_state_and_world_placement',async()=>{
 const f=basic('fountain',{at:[12,14,2],entity:'switch.pump',sensor:'sensor.rpm',sensor_min:1000,sensor_max:3450});
 const out=buildEffects(planWith(f));assert.equal(out.fixtures[0].active,false);
 const states={'switch.pump':{state:'on'},'sensor.rpm':{state:'2225'}};out.update(states,false,1);out.update(states,false,1.5);
 const row=out.fixtures[0];assert.deepEqual(row.position,[12,14,2]);assert.equal(row.active,true);assert.ok(row.opacity>0&&row.opacity<1);
 assert.ok(row.t>.5&&row.t<1);out.update(states,false,2);assert.equal(row.t,.5);assert.equal(row.size,3.5);
 out.update({},true,3);assert.equal(row.active,false);assert.equal(row.group.visible,true);out.update({},true,4);assert.equal(row.group.visible,false);
});
await test('effects_survive_static_merge_and_never_receive_or_occlude_bake',async()=>{
 const out=buildEffects(planWith(...['waterfall','fountain','bubbler','fire'].map(type=>basic(type))),{editor:true});
 const rows=effectMeshes(out.group),original=rows.map(mesh=>[mesh.uuid,mesh.geometry.uuid]);G.mergeStatic(out.group);
 assert.deepEqual(effectMeshes(out.group).map(mesh=>[mesh.uuid,mesh.geometry.uuid]),original);
 for(const mesh of rows){assert.equal(A.atlasMesh(mesh),false);assert.ok(!mesh.userData.merged);}
 const scene=new THREE.Scene();scene.add(out.group);assert.equal(occluders({scene}).children.length,0);
});
await test('no_effects_adds_no_scene_objects_or_draw_calls',async()=>{
 assert.equal(buildEffects({buildings:[],site:{}}),null);assert.equal(buildEffects(planWith()),null);
 const p=fixture(),a=await build(p),b=await build({...p,effect_fixtures:[]});assert.equal(a.effects,null);assert.equal(b.effects,null);
 assert.deepEqual(signature(a),signature(b));assert.equal(rendered(a).length,rendered(b).length);
});
await test('build_twin_includes_effect_group_and_keeps_two_draws',async()=>{
 const p=fixture();p.effect_fixtures=[basic('fountain')];const out=await build(p);assert.ok(out.effects);assert.ok(out.root.getObjectByName('effect-fixtures'));
 assert.equal(effectMeshes(out.effects.group).length,2);assert.ok(effectMeshes(out.effects.group).every(mesh=>!mesh.userData.merged));
});
await test('mounted_view_frame_hook_advances_effect_time',async()=>{
 const old=Renderer.prototype.setAnimationLoop;Renderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
 const oldSearch=location.search;location.search='?test=1&tier=high';
 const p=fixture();p.effect_fixtures=[basic('fountain')];let view;
 try{view=await mountTwin(new Element(),{plan:p,kit:kit(),tier:'high',bake:false});
  const effects=view.scene.getObjectByName('effect-fixtures');assert.ok(effects);const u=uniforms(effects)[0];const before=u.time.value;
  assert.equal(typeof view.renderer3.loop,'function');view.renderer3.loop();assert.ok(u.time.value>before);
 }finally{view?.dispose();Renderer.prototype.setAnimationLoop=old;location.search=oldSearch;}
});
finish();
"""


def run():
    node = shutil.which('node')
    assert node, 'Node is required'
    scratch = ROOT / '.tmp-effects'
    scratch.mkdir(exist_ok=True)
    tag = 'effect-visuals-' + uuid.uuid4().hex
    script, payload = scratch / (tag + '.mjs'), scratch / (tag + '.json')
    try:
        script.write_text(DRIVER, encoding='utf-8')
        payload.write_text(json.dumps({'root': ROOT.as_posix(), 'editable': True}), encoding='utf-8')
        result = subprocess.run([node, str(script), str(payload)], capture_output=True,
                                text=True, encoding='utf-8', timeout=180)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode
    finally:
        script.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
