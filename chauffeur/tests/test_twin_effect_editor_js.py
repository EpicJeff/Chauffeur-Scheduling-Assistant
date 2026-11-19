"""Run effect placement, linked entity fields and selection through the real editor."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from twin_editor_dom import PRELUDE

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const {createFixtureEditor}=await import(file('static/twin/editor/fixtures.js'));
const evt=(x,y=10)=>({clientX:x,clientY:y,button:0,pointerId:1});
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const id='effect:00000000-0000-4000-8000-000000000001';
const base=()=>({id,type:'fountain',shape:'point',ref:'ground',at:[10,10,0]});
function setup(fixtures=[]){
 const plan={buildings:[],site:{lot:[[0,0],[100,0],[100,100],[0,100]],terraces:[]},effect_fixtures:fixtures};
 const sent=[],errors=[],choices=[],prompts=[],signal=new AbortController(),canvas=document.createElement('canvas');let editable=true;
 const view={scene:new THREE.Group(),renderer3:{domElement:canvas},controls:{enabled:true},camera:new THREE.PerspectiveCamera(60,1440/900,.01,1000),pick:()=>null};
 document.body.append(canvas);view.camera.position.set(15,25,15);view.camera.lookAt(3,0,-3);view.camera.updateMatrixWorld(true);
 const bar=document.getElementById('device-tools');bar.replaceChildren();const done=document.createElement('button');done.id='device-cancel';bar.append(document.getElementById('device-note'),done);
 document.getElementById('piece-card').replaceChildren();
 globalThis.fetch=async()=>{throw new Error('HA absent');};
 window.promptChoice=async(...args)=>{prompts.push(args);return choices.shift()??null;};
 window.promptInput=async()=>null;window.promptConfirm=async()=>true;
 const options={view,tools:{setTool(){},select(){},selection:()=>({}),haLink:{state:()=>({devices:[]})}},library:{surfaceAt:()=>null,ground:e=>[e.clientX,e.clientY]},
  getPlan:()=>plan,op:async o=>sent.push(o),canEdit:()=>editable,signal:signal.signal,report:e=>errors.push(String(e))};
 const editor=createFixtureEditor(options);
 return {plan,sent,errors,choices,prompts,view,editor,signal,library:options.library,lock:()=>{editable=false;},card:()=>document.getElementById('piece-card')};
}
async function change(s,label,value){
 const field=s.card().querySelector(`[aria-label="${label}"]`);assert.ok(field,label);field.value=String(value);await fire(field,'change');await settle();
}
async function place(s,x,y=10){s.editor.pointerDown(evt(x,y));await s.editor.pointerUp(evt(x,y));}
await test('add_point_uses_choice_and_existing_surface_placement',async()=>{
 const s=setup();try{s.choices.push('fountain');await s.editor.addEffect('switch.pump');assert.equal(s.editor.active(),true);
 assert.deepEqual(s.prompts[0][2].map(o=>o.value),['waterfall','fountain','bubbler','fire','spa_jet','steam','sheer','deck_jet','mist']);
 await place(s,10,12);assert.deepEqual(s.sent,[{op:'add_effect_fixture',fixture:{type:'fountain',shape:'point',ref:'ground',at:[10,12,0],entity:'switch.pump'}}]);
 }finally{s.signal.abort();}
});
await test('a_click_on_pool_water_places_on_the_ground_under_it',async()=>{
 // The Library's surface pick answers pool and spa water with no building and no point.
 const s=setup();try{s.library.surfaceAt=()=>({kind:'pool',piece:{id:'pool'},role:'water',target:{pool:'pool',part:'water'},label:'Pool water'});
 s.choices.push('bubbler');await s.editor.addEffect();await place(s,10,12);assert.deepEqual(s.errors,[]);
 assert.deepEqual(s.sent,[{op:'add_effect_fixture',fixture:{type:'bubbler',shape:'point',ref:'ground',at:[10,12,0]}}]);
 }finally{s.signal.abort();}
});
await test('add_waterfall_runs_existing_polyline_tool_and_one_op',async()=>{
 const s=setup();try{s.choices.push('waterfall');await s.editor.addEffect();await place(s,10);await place(s,20);assert.equal(s.sent.length,0);
 await fire(document,'keydown',{key:'Enter'});await settle();assert.equal(s.sent.length,1);
 const out=s.sent[0];assert.equal(out.op,'add_effect_fixture');assert.equal(out.fixture.type,'waterfall');assert.equal(out.fixture.shape,'line');
 assert.deepEqual(out.fixture.path,[[10,10,0],[20,10,0]]);assert.equal(out.fixture.entity,undefined);assert.equal(out.fixture.width_in,undefined);
 }finally{s.signal.abort();}
});
await test('floor_placement_preserves_the_existing_level_reference',async()=>{
 const s=setup();try{const building={id:'a',position:[5,6],base:0,levels:[{id:'L2',elevation:8,ceiling:8}]};s.plan.buildings.push(building);
 s.library.surfaceAt=()=>({building,point:[2,3,9],level:'L2',kind:'room',surface:'floor'});
 s.choices.push('fountain');await s.editor.addEffect();await place(s,10);
 // A floor click stands one inch off the surface, exactly as a point light does.
 assert.equal(s.sent.length,1);const {at,...rest}=s.sent[0].fixture;
 assert.deepEqual({op:s.sent[0].op,fixture:rest},{op:'add_effect_fixture',fixture:{type:'fountain',shape:'point',ref:'floor',building:'a',level:'L2'}});
 assert.deepEqual(at.slice(0,2),[7,9]);assert.ok(Math.abs(at[2]-(1+1/12))<1e-9);
 }finally{s.signal.abort();}
});
await test('waterfall_snap_uses_shared_fence_edge_tool',async()=>{
 const s=setup();try{s.plan.site.fence=[{id:'fence',polyline:[[10,60],[20,60]],height:6}];s.choices.push('waterfall');await s.editor.addEffect('switch.pump');
 await click(byText(document.getElementById('device-tools'),'Snap to edge'));
 const project=p=>{const v=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(s.view.camera);return evt((v.x+1)*720,(1-v.y)*450);};
 s.editor.pointerMove(project([15,60,6]));s.editor.pointerDown(project([12.5,60,6]));s.editor.pointerMove(project([17.5,60,6]));await s.editor.pointerUp(project([17.5,60,6]));
 assert.equal(s.sent.length,1);const f=s.sent[0].fixture;assert.equal(f.type,'waterfall');assert.equal(f.entity,'switch.pump');
 assert.equal(f.snap.host.kind,'fence');assert.equal(f.snap.host.id,'fence');assert.ok(Math.abs(f.snap.t0-.25)<1e-5);assert.ok(Math.abs(f.snap.t1-.75)<1e-5);
 assert.ok(f.path.every(p=>Math.abs(p[1]-60)<1e-5&&Math.abs(p[2]-6)<1e-5));assert.equal(f.width_in,undefined);
 }finally{s.signal.abort();}
});
await test('fire_choice_can_place_a_point_or_draw_a_line',async()=>{
 for(const shape of ['point','line']){const s=setup();try{s.choices.push('fire',shape);await s.editor.addEffect('fan.fire');
 assert.deepEqual(s.prompts[1][2].map(o=>o.value),['point','line']);await place(s,10);
 if(shape==='line'){await place(s,20);await fire(document,'keydown',{key:'Enter'});await settle();}
 assert.equal(s.sent.length,1);assert.equal(s.sent[0].fixture.type,'fire');assert.equal(s.sent[0].fixture.shape,shape);assert.equal(s.sent[0].fixture.entity,'fan.fire');
 }finally{s.signal.abort();}}
});
await test('cancel_choice_and_escape_leave_no_ops',async()=>{
 const s=setup();try{await s.editor.addEffect();assert.equal(s.editor.active(),false);s.choices.push('bubbler');await s.editor.addEffect();
 await fire(document,'keydown',{key:'Escape'});assert.equal(s.editor.active(),false);assert.equal(s.sent.length,0);
 }finally{s.signal.abort();}
});
await test('card_changes_each_send_exactly_one_update',async()=>{
 const s=setup([base()]);try{s.editor.showEffect(id);
 for(const [label,value,delta]of [['Name','Spill',{name:'Spill'}],['Type','fire',{type:'fire'}],['Switch','switch.fire',{entity:'switch.fire'}],
  ['Offset (ft)',-1,{offset_ft:-1}],['Size at min (ft)',.5,{size_min:.5}],['Size at max (ft)',4,{size_max:4}],['Level (%)',25,{strength:.25}]]){
  const before=s.sent.length;await change(s,label,value);assert.equal(s.sent.length,before+1);assert.deepEqual(s.sent.at(-1),{op:'update_effect_fixture',id,change:delta});
 }
 assert.deepEqual(s.errors,[]);
 }finally{s.signal.abort();}
});
await test('sensor_link_prompts_both_bounds_before_one_save',async()=>{
 const s=setup([base()]);try{const prompts=[],answers=['1000','3450'];window.promptInput=async(...args)=>{prompts.push(args);return answers.shift();};
 s.editor.showEffect(id);assert.equal(s.card().querySelector('[aria-label="Sensor min"]'),null);await change(s,'Sensor','sensor.rpm');
 assert.equal(prompts.length,2);assert.equal(prompts[0][2].value,'0');assert.equal(prompts[1][2].value,'100');
 assert.deepEqual(s.sent,[{op:'update_effect_fixture',id,change:{sensor:'sensor.rpm',sensor_min:1000,sensor_max:3450}}]);
 }finally{s.signal.abort();}
});
await test('sensor_prompt_cancel_sends_nothing',async()=>{
 for(const answers of [[null],['0',null]]){const s=setup([base()]);try{window.promptInput=async()=>answers.shift();s.editor.showEffect(id);
 await change(s,'Sensor','sensor.rpm');assert.equal(s.sent.length,0);assert.equal(s.card().querySelector('[aria-label="Sensor"]').value,'');
 }finally{s.signal.abort();}}
});
await test('linked_sensor_bounds_and_clear_buttons_have_one_op',async()=>{
 const s=setup([{...base(),sensor:'sensor.rpm',sensor_min:1000,sensor_max:3450,entity:'switch.pump'}]);try{s.editor.showEffect(id);
 await change(s,'Sensor min',900);assert.deepEqual(s.sent.at(-1).change,{sensor_min:900});
 await change(s,'Sensor max',3500);assert.deepEqual(s.sent.at(-1).change,{sensor_max:3500});
 await click(byText(s.card(),'Clear sensor'));await settle();assert.deepEqual(s.sent.at(-1).change,{sensor:null,sensor_min:null,sensor_max:null});
 await click(byText(s.card(),'Clear switch'));await settle();assert.deepEqual(s.sent.at(-1).change,{entity:null});assert.equal(s.sent.length,4);
 }finally{s.signal.abort();}
});
await test('waterfall_drop_allows_manual_and_automatic_and_delete',async()=>{
 const s=setup([{id,type:'waterfall',shape:'line',ref:'absolute',path:[[10,10,3],[20,10,3]]}]);try{s.editor.showEffect(id);
 await change(s,'Drop (ft)',5);assert.deepEqual(s.sent.at(-1).change,{drop_ft:5});await change(s,'Drop (ft)','');assert.deepEqual(s.sent.at(-1).change,{drop_ft:null});
 await click(byText(s.card(),'Delete'));await settle();assert.deepEqual(s.sent.at(-1),{op:'delete_effect_fixture',id});assert.equal(s.sent.length,3);
 }finally{s.signal.abort();}
});
await test('no_ha_keeps_entity_text_fields_editable',async()=>{
 const s=setup([base()]);try{s.editor.showEffect(id);await settle();
 for(const label of ['Switch','Sensor']){const field=s.card().querySelector(`[aria-label="${label}"]`);assert.ok(field);assert.equal(field.disabled,false);assert.ok(field.getAttribute('list'));}
 await change(s,'Switch','input_boolean.test');assert.deepEqual(s.sent.at(-1).change,{entity:'input_boolean.test'});
 }finally{s.signal.abort();}
});
await test('linked_effect_card_reached_through_existing_device_fixtures',async()=>{
 const s=setup([{...base(),entity:'switch.pump'}]);try{s.editor.showDevice({device_id:'pump',entity_id:'switch.pump',name:'Pump'});
 assert.ok(s.card().querySelector('[data-effect-id]'));assert.ok(byText(s.card(),'Add effect'));await change(s,'Level (%)',50);assert.deepEqual(s.sent.at(-1).change,{strength:.5});
 }finally{s.signal.abort();}
});
await test('effect_pick_opens_its_card_and_read_only_blocks_placement',async()=>{
 const s=setup([base()]);try{s.editor.refresh();const v=new THREE.Vector3(10*.3048,0,-10*.3048).project(s.view.camera);
 const e=evt((v.x+1)*720,(1-v.y)*450);assert.equal(s.editor.pointerDown(e),true);await s.editor.pointerUp(e);
 assert.ok(s.card().querySelector('[data-effect-id]'));s.lock();s.editor.refresh();
 assert.ok(s.card().querySelectorAll('input,select').every(field=>field.disabled));s.choices.push('fountain');await s.editor.addEffect();assert.equal(s.editor.active(),false);assert.equal(s.sent.length,0);
 }finally{s.signal.abort();}
});
await test('new_type_placement_and_mist_shapes_keep_one_op_and_heater_link',async()=>{
 for(const [type,shape] of [['spa_jet','point'],['steam','point'],['sheer','line'],['deck_jet','point'],['mist','point'],['mist','line']]){
  const s=setup();try{s.choices.push(type,...(type==='mist'?[shape]:[]));await s.editor.addEffect('climate.spa');await place(s,10);
   if(shape==='line'){await place(s,20);await fire(document,'keydown',{key:'Enter'});await settle();}
   assert.equal(s.sent.length,1);assert.equal(s.sent[0].fixture.type,type);assert.equal(s.sent[0].fixture.shape,shape);assert.equal(s.sent[0].fixture.entity,'climate.spa');
  }finally{s.signal.abort();}
 }
});
await test('type_list_is_shape_specific_and_sheer_has_drop',async()=>{
 for(const shape of ['point','line']){const s=setup([{...base(),type:shape==='line'?'sheer':'steam',shape,...(shape==='line'?{path:[[10,10,3],[20,10,3]],at:undefined}:{})}]);
  try{s.editor.showEffect(id);const types=s.card().querySelector('[aria-label="Type"]').querySelectorAll('option').map(n=>n.value);
   assert.deepEqual(types,shape==='point'?['fountain','bubbler','fire','spa_jet','steam','deck_jet','mist']:['waterfall','fire','sheer','mist']);
   assert.ok(s.card().querySelector('[aria-label="Attribute"]'));assert.equal(s.card().querySelector('[aria-label="Attribute"]').value,'');
   if(shape==='line'){await change(s,'Drop (ft)',2);assert.deepEqual(s.sent.at(-1).change,{drop_ft:2});}
  }finally{s.signal.abort();}
 }
});
await test('attribute_box_suggests_only_numeric_values_and_saves_one_op',async()=>{
 const s=setup([{...base(),sensor:'climate.spa',sensor_attribute:'current_temperature',sensor_min:70,sensor_max:100}]);
 try{globalThis.fetch=async url=>({ok:true,json:async()=>url.endsWith('card/states')?{states:{'climate.spa':{attributes:{current_temperature:85,temperature:'100',friendly_name:'Spa',empty:'',flag:true,options:[],missing:null}}}}:[]});
  s.editor.showEffect(id);await settle();const input=s.card().querySelector('[aria-label="Attribute"]');
  assert.equal(input.value,'current_temperature');assert.equal(input.disabled,false);
  assert.deepEqual(input.parentElement.querySelectorAll('option').map(n=>n.value),['current_temperature','temperature']);
  await change(s,'Attribute','temperature');assert.deepEqual(s.sent,[{op:'update_effect_fixture',id,change:{sensor_attribute:'temperature'}}]);
 }finally{s.signal.abort();}
});
await test('no_ha_attribute_text_and_extended_sensor_link_are_atomic',async()=>{
 const s=setup([base()]);try{const answers=['percentage','0','100'];window.promptInput=async()=>answers.shift();s.editor.showEffect(id);
  await change(s,'Sensor','fan.spa');assert.deepEqual(s.sent,[{op:'update_effect_fixture',id,change:{sensor:'fan.spa',sensor_min:0,sensor_max:100,sensor_attribute:'percentage'}}]);
  Object.assign(s.plan.effect_fixtures[0],s.sent[0].change);s.editor.refresh();await settle();
  assert.equal(s.card().querySelector('[aria-label="Attribute"]').disabled,false);
  await change(s,'Attribute','custom_value');assert.equal(s.sent.length,2);assert.deepEqual(s.sent[1].change,{sensor_attribute:'custom_value'});
 }finally{s.signal.abort();}
});
await test('spa_jet_off_water_card_explains_and_heater_device_opens_card',async()=>{
 const s=setup([{...base(),type:'spa_jet',entity:'water_heater.spa'}]);try{s.editor.showDevice({device_id:'spa',entity_id:'water_heater.spa',name:'Spa heater'});
  assert.ok(textOf(s.card()).includes('Spa jet needs pool or spa water within 3 ft.'));assert.ok(byText(s.card(),'Add effect'));
 }finally{s.signal.abort();}
});
finish();
"""


def run():
    node = shutil.which('node')
    assert node, 'Node is required'
    scratch = ROOT / '.tmp-effects'
    scratch.mkdir(exist_ok=True)
    tag = 'effect-editor-' + uuid.uuid4().hex
    script, payload = scratch / (tag + '.mjs'), scratch / (tag + '.json')
    try:
        script.write_text(DRIVER, encoding='utf-8')
        payload.write_text(json.dumps({'root': ROOT.as_posix()}), encoding='utf-8')
        result = subprocess.run([node, str(script), str(payload)], capture_output=True,
                                text=True, encoding='utf-8', timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode
    finally:
        script.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
