"""Task 6: execute production fixture drawing, snapping, cards and scene picking."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import('three');
const snapChecks=[],keepChecks=[];
const modules=()=>import(file('static/twin/editor/fixtures.js'));
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
const evt=(x,y=10)=>({clientX:x,clientY:y,button:0,pointerId:1});
const fid='fixture:00000000-0000-4000-8000-000000000001';
const line={id:fid,shape:'line',ref:'absolute',path:[[10,10,2],[20,10,2]],facing:'down',width_in:.5};
function setup(){
 const b={id:'b',position:[40,40],rotation:90,base:0,levels:[{id:'L1',elevation:0,ceiling:9}],joints:[{id:'j1',at:[0,0]},{id:'j2',at:[10,0]}],
  walls:[{id:'w',level:'L1',joints:['j1','j2'],from:[0,0],to:[10,0],thickness:.5}],rooms:[],
  stairs:[{id:'s',level:'L1',from:[0,10],to:[4,10],width:4,risers:4,rise_to:4}]};
 const plan={buildings:[b],site:{lot:[[0,0],[100,0],[100,100],[0,100]],
  terraces:[{id:'pad',height:2,polygon:[[10,10],[20,10],[20,20],[10,20]],edges:[{edge:'sharp',wall:{above_in:6}},{edge:'slope'},{edge:'slope'},{edge:'slope'}]}],
  hardscape:[{id:'patio',elevation:1,polygon:[[60,10],[70,10],[70,20],[60,20]]}],fence:[{id:'fence',polyline:[[10,60],[20,60]],height:6}]},light_fixtures:{'light.a':[]}};
 const sent=[],errors=[],canvas=document.createElement('canvas'),view={scene:new THREE.Group(),renderer3:{domElement:canvas},controls:{enabled:true},camera:new THREE.PerspectiveCamera(60,1440/900,.01,1000),pick:()=>null};
 document.body.append(canvas);view.camera.position.set(50*.3048,50,-50*.3048);view.camera.lookAt(50*.3048,0,-50*.3048);view.camera.updateMatrixWorld(true);
 const bar=document.getElementById('device-tools');bar.replaceChildren();const done=document.createElement('button');done.id='device-cancel';bar.append(document.getElementById('device-note'),done);
 const signal=new AbortController();let editable=true;const library={surfaceAt:()=>null,ground:e=>[e.clientX,e.clientY]};
 return {plan,sent,errors,view,library,signal,canEdit:()=>editable,lock:()=>editable=false,getPlan:()=>plan,
  op:async o=>{sent.push(o);},prepare(){},tools:{setTool(){},select(){},haLink:{state:()=>({devices:[]})}}};
}
async function editor(s){const {createFixtureEditor}=await modules();return createFixtureEditor({...s,signal:s.signal.signal,report:e=>s.errors.push(String(e))});}
const card=async(s,more={})=>(await modules()).fixtureCard({entity_id:'light.a',getPlan:s.getPlan,canEdit:s.canEdit,op:s.op,...more});
const project=(s,p)=>{const v=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(s.view.camera);return evt((v.x+1)*720,(1-v.y)*450);};
async function snapRun(s,e,kind,existing,facing){
 const {snapEdges}=await import(file('static/twin/editor/line_fixture_tool.js'));const edge=snapEdges(s.plan).find(v=>v.host.kind===kind);assert.ok(edge,kind);
 if(existing){e.showDevice({device_id:'d',entity_id:'light.a',name:'Lamp'},existing.id);await click(byText(document.getElementById('piece-card'),'Reattach'));}else{e.add('light.a','line');await click(byText(document.getElementById('device-tools'),'Snap to edge'));}
 if(facing){const select=document.getElementById('device-tools').querySelector('[aria-label="Facing"]');select.value=facing;await fire(select,'change');}
 const at=t=>edge.a.map((v,i)=>v+(edge.b[i]-v)*t+(i===2?(edge.lift||0):0));
 e.pointerMove(project(s,at(.5)));assert.equal(s.sent.length,0);e.pointerDown(project(s,at(.25)));e.pointerMove(project(s,at(.75)));await e.pointerUp(project(s,at(.75)));
 const value=s.sent.at(-1)?.fixture||s.sent.at(-1)?.change;if(value)snapChecks.push({plan:s.plan,value});return {edge,value};
}
await test('snap_to_retaining_wall_cap_sets_snap_and_path',async()=>{
 const s=setup(),e=await editor(s),{value}=await snapRun(s,e,'retaining_wall');
 assert.equal(s.sent.length,1);assert.equal(value.snap.host.kind,'retaining_wall');assert.deepEqual(value.snap.edge,{from:[10,10],to:[20,10]});
 assert.ok(Math.abs(value.snap.t0-.25)<1e-5);assert.ok(Math.abs(value.snap.t1-.75)<1e-5);assert.ok(value.path.every(p=>p[1]===10&&p[2]===2.5));s.signal.abort();
});
for(const kind of ['hardscape','fence','step','wall'])await test('snap_'+kind+'_stores_raw_host_without_facing_offset',async()=>{
 const s=setup(),e=await editor(s),{value,edge}=await snapRun(s,e,kind);assert.equal(s.sent.length,1);assert.equal(value.snap.host.kind,kind);
 for(const [i,t]of [value.snap.t0,value.snap.t1].entries())for(let k=0;k<3;k++)assert.ok(Math.abs(value.path[i][k]-(edge.a[k]+(edge.b[k]-edge.a[k])*t))<1e-5,JSON.stringify({value,edge}));
 s.signal.abort();
});
await test('facing_select_updates_once',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[{...line,snap:{host:{kind:'wall',id:'w'},edge:{from:[40,40],to:[40,50]},t0:0,t1:1}}];
 const n=await card(s),f=n.querySelector('[aria-label="Facing"]');assert.ok(f);assert.ok(f.children.some(n=>n.value==='out'));assert.ok(f.children.some(n=>n.value==='in'));
 f.value='in';await fire(f,'input');assert.equal(s.sent.length,0);await fire(f,'change');assert.equal(s.sent.length,1);assert.deepEqual(s.sent[0].change,{facing:'in'});
 s.plan.light_fixtures['light.a'][0].snap.host.kind='step';const step=await card(s),select=step.querySelector('[aria-label="Facing"]');assert.deepEqual(select.children.map(n=>n.value),['down','out']);assert.equal(select.value,'down');assert.ok(select.children[0].disabled);assert.ok(textOf(select).includes('Downhill'));
});
await test('snap_mode_honours_facing_chosen_before_pick',async()=>{
 const s=setup(),e=await editor(s),{value}=await snapRun(s,e,'hardscape',null,'up');assert.equal(value.facing,'up');assert.equal(s.sent.length,1);s.signal.abort();
});
await test('area_rectangle_commits_size_and_facing',async()=>{
 const s=setup();s.plan.site.terraces=[];const e=await editor(s);e.add('light.a','area');e.pointerDown(evt(10,10));e.pointerMove(evt(16,14));await e.pointerUp(evt(16,14));assert.equal(s.sent.length,0);
 const facing=document.getElementById('device-tools').querySelector('[aria-label="Facing"]');facing.value='up';await fire(facing,'change');await click(byText(document.getElementById('device-tools'),'Finish'));
 assert.equal(s.sent.length,1);assert.ok(s.sent[0].fixture.at.every((v,i)=>Math.abs(v-[13,12,0][i])<1e-8));assert.ok(s.sent[0].fixture.size_ft.every((v,i)=>Math.abs(v-[6,4][i])<1e-8));assert.equal(s.sent[0].fixture.facing,'up');s.signal.abort();
});
await test('polyline_backspace_enter_is_one_op',async()=>{
 const s=setup();s.plan.site.terraces=[];const e=await editor(s);e.add('light.a','line');for(const x of [10,20,30]){e.pointerDown(evt(x));await e.pointerUp(evt(x));}assert.equal(s.sent.length,0);
 await fire(document,'keydown',{key:'Backspace'});await fire(document,'keydown',{key:'Enter'});assert.equal(s.sent.length,1);assert.deepEqual(s.sent[0].fixture.path,[[10,10,0],[20,10,0]]);s.signal.abort();
});
await test('escape_mid_draw_and_drag_sends_no_op_then_idle_exits',async()=>{
 const s=setup(),e=await editor(s);e.add('light.a','line');e.pointerDown(evt(10));await e.pointerUp(evt(10));await fire(document,'keydown',{key:'Escape'});
 assert.equal(e.active(),true);assert.equal(s.sent.length,0);await fire(document,'keydown',{key:'Escape'});assert.equal(e.active(),false);
 e.add('light.a','area');e.pointerDown(evt(10));e.pointerMove(evt(20));await fire(document,'keydown',{key:'Escape'});assert.equal(e.active(),true);assert.equal(s.view.controls.enabled,true);assert.equal(e.pointerUp(evt(20)),false);assert.equal(s.sent.length,0);s.signal.abort();
});
await test('detached_row_offers_reattach_and_keep_as_drawn',async()=>{
 const s=setup(),reattach=[];s.plan.light_fixtures['light.a']=[{...line,detached:true,snap:{host:{kind:'wall',id:'gone'},edge:{from:[0,0],to:[10,0]},t0:0,t1:1}}];
 const n=await card(s,{onReattach:(...v)=>reattach.push(v)});assert.ok(textOf(n).includes('Detached'));await click(byText(n,'Reattach'));assert.equal(reattach[0][1].id,fid);
 await click(byText(n,'Keep as drawn'));assert.equal(s.sent.at(-1).change.snap,null);assert.equal(s.sent.at(-1).change.ref,'absolute');
});
await test('reattach_keeps_fixture_id',async()=>{
 const s=setup(),e=await editor(s),f={...line,detached:true,snap:{host:{kind:'wall',id:'gone'},edge:{from:[0,0],to:[10,0]},t0:0,t1:1}};
 s.plan.light_fixtures['light.a']=[f];await snapRun(s,e,'hardscape',f);assert.equal(s.sent.length,1);assert.equal(s.sent[0].op,'update_light_fixture');assert.equal(s.sent[0].id,fid);s.signal.abort();
});
await test('non_parent_line_and_area_rows_are_read_only',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[line,{id:'area',shape:'area',ref:'absolute',at:[10,10,2],size_ft:[4,3],facing:'up',rotation_deg:0}];s.lock();
 const n=await card(s);assert.ok(n.querySelectorAll('input,select,button').every(n=>n.disabled));for(const b of n.querySelectorAll('button'))await click(b);assert.equal(s.sent.length,0);
 const e=await editor(s);for(const shape of ['line','area'])e.add('light.a',shape);assert.equal(e.active(),false);s.signal.abort();
});
await test('number_fields_show_at_most_two_decimals_without_rewriting',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[{...line,path:[[10.123456,10,2],[20,10,2]],share:1.234567},{id:'area',shape:'area',ref:'absolute',at:[10.123456,10,2],size_ft:[4.987654,3],facing:[.123456,0,.99235],rotation_deg:12.345678}];
 s.plan.light_fixtures['light.a'].push({id:'point',shape:'point',ref:'absolute',at:[107.55075907197178,10,2]},{id:'spot',shape:'spot',ref:'absolute',at:[10.987654,10,2],aim:[20.123456,10,0],cone_deg:91.123456,softness:.312345});
 const before=structuredClone(s.plan),n=await card(s);assert.ok(n.querySelectorAll('input[type="number"]').every(n=>!String(n.value).includes('.')||String(n.value).split('.')[1].length<=2));assert.deepEqual(s.plan,before);assert.equal(s.sent.length,0);
});
await test('line_and_area_rows_edit_geometry_and_duplicate',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[line,{id:'area',shape:'area',ref:'absolute',at:[10,10,2],size_ft:[4,3],facing:[0,1,0],rotation_deg:0}];const n=await card(s);
 const rows=n.querySelectorAll('[data-fixture-id]');assert.ok(byText(rows[0],'Redraw'));assert.ok(byText(rows[1],'Move'));assert.ok(rows[0].querySelector('[aria-label="Point 1 east (ft)"]'));
 const width=rows[1].querySelector('[aria-label="Width (ft)"]');width.value='8';await fire(width,'change');assert.deepEqual(s.sent.at(-1).change,{size_ft:[8,3]});
 await click(byText(rows[0],'Duplicate'));assert.equal(s.sent.at(-1).fixture.id,undefined);assert.deepEqual(s.sent.at(-1).fixture.path,line.path);
});
await test('raw_line_and_area_reuse_wall_and_slab_standoff',async()=>{
 const s=setup();s.plan.site.terraces=[];const b=s.plan.buildings[0];b.position=[0,0];b.rotation=0;const e=await editor(s);
 for(const side of ['left','right']){
  s.library.surfaceAt=ev=>({building:b,point:[ev.clientX,0,ev.clientY],level:'L1',kind:'wall',piece:b.walls[0],side});
  e.add('light.a','line');for(const x of [2,8]){e.pointerDown(evt(x,4));await e.pointerUp(evt(x,4));}await fire(document,'keydown',{key:'Enter'});
  const f=s.sent.at(-1).fixture;assert.ok(f.path.every(p=>Math.abs(p[1]-(side==='left'?1:-1)*(.25+1/12))<.00051));
  e.add('light.a','area');e.pointerDown(evt(2,2));e.pointerMove(evt(8,6));await e.pointerUp(evt(8,6));await click(byText(document.getElementById('device-tools'),'Finish'));
  const area=s.sent.at(-1).fixture;assert.equal(area.shape,'area');assert.ok(Math.abs(area.at[1]-(side==='left'?1:-1)*(.25+1/12))<1e-8);assert.ok(area.facing.every((v,i)=>Math.abs(v-[0,side==='left'?1:-1,0][i])<1e-8));
 }
 for(const surface of ['floor','ceiling']){
  s.library.surfaceAt=ev=>({building:b,point:[ev.clientX,ev.clientY,surface==='floor'?0:9],level:'L1',kind:'room',surface});
  e.add('light.a','area');e.pointerDown(evt(2,2));e.pointerMove(evt(8,6));await e.pointerUp(evt(8,6));await click(byText(document.getElementById('device-tools'),'Finish'));
  assert.ok(Math.abs(s.sent.at(-1).fixture.at[2]-(surface==='floor'?1/12:9-1/12))<1e-8);
 }s.signal.abort();
});
await test('line_and_area_markers_are_paths_pickable_read_only_hidden_and_occluded',async()=>{
 for(const shape of ['line','area']){
  const s=setup();s.plan.site.terraces=[];s.plan.light_fixtures['light.a']=[shape==='line'?{...line,ref:'floor',building:'b',level:'L1'}:{id:fid,shape:'area',ref:'floor',building:'b',level:'L1',at:[15,10,2],size_ft:[10,4],facing:'up',rotation_deg:0}];
  s.view.groups={levels:{'b:L1':{visible:true}}};const e=await editor(s);e.refresh();const marker=s.view.scene.getObjectByName('editor-light-fixtures').children.find(c=>c.userData.fixtureId);assert.equal(marker.isMesh,true);assert.equal(marker.material.depthTest,true);assert.ok(marker.geometry.attributes.position.count>=18);marker.geometry.computeBoundingBox();assert.ok(marker.geometry.boundingBox.max.y-marker.geometry.boundingBox.min.y>.1);
  const target=shape==='line'?[15,10,2]:[15,12,2],event=project(s,target);s.lock();assert.equal(e.pointerDown(event),true);await e.pointerUp(event);
  assert.ok(document.getElementById('piece-card').querySelector(`[data-fixture-id="${fid}"]`).open);assert.equal(s.sent.length,0);
  s.view.groups.levels['b:L1'].visible=false;e.draw();assert.equal(marker.visible,false);assert.equal(e.pointerDown(event),false);
  s.view.groups.levels['b:L1'].visible=true;s.view.pick=()=>({point:[s.view.camera.position.x,s.view.camera.position.y-1,s.view.camera.position.z]});assert.equal(e.pointerDown(event),false);s.signal.abort();
 }
});
await test('failed_area_save_retries_once_and_permission_loss_cancels',async()=>{
 const s=setup(),sent=s.op;let fail=true;s.op=async o=>{if(fail)throw Error('offline');return sent(o);};const e=await editor(s);
 e.add('light.a','area');e.pointerDown(evt(2,2));e.pointerMove(evt(8,6));await e.pointerUp(evt(8,6));await click(byText(document.getElementById('device-tools'),'Finish'));assert.equal(s.sent.length,0);assert.ok(s.errors.some(v=>v.includes('offline')));assert.equal(e.active(),true);
 fail=false;await click(byText(document.getElementById('device-tools'),'Finish'));assert.equal(s.sent.length,1);assert.equal(e.active(),false);
 e.add('light.a','line');e.pointerDown(evt(10));await e.pointerUp(evt(10));s.lock();e.refresh();await fire(document,'keydown',{key:'Enter'});assert.equal(s.sent.length,1);assert.equal(e.active(),false);s.signal.abort();
});
await test('pending_line_save_does_not_cancel_a_new_placement_mode',async()=>{
 const s=setup();let release;const send=s.op;s.op=o=>new Promise(resolve=>release=()=>{send(o);resolve();});const e=await editor(s);
 e.add('light.a','line');for(const x of [2,8]){e.pointerDown(evt(x));await e.pointerUp(evt(x));}await fire(document,'keydown',{key:'Enter'});assert.ok(release);
 e.add('light.a','point');release();await new Promise(resolve=>setImmediate(resolve));assert.equal(e.active(),true);s.signal.abort();
});
await test('numeric_edits_preserve_other_full_precision_coordinates',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[{...line,path:[[10.123456,10.987654,2.123456],[20,10,2]],share:1.234567}];const n=await card(s),input=n.querySelector('[aria-label="Point 1 east (ft)"]');input.value='12.5';await fire(input,'change');assert.deepEqual(s.sent[0].change.path,[[12.5,10.987654,2.123456],[20,10,2]]);
});
await test('drawn_floor_shapes_keep_level_reference_and_hide_with_it',async()=>{
 const s=setup();s.plan.site.terraces=[];const b=s.plan.buildings[0];b.levels[0].elevation=9;b.base=2;b.rotation=0;b.position=[0,0];
 s.library.surfaceAt=ev=>({building:b,point:[ev.clientX,ev.clientY,13],level:'L1',kind:'room',surface:'floor'});const e=await editor(s);
 for(const shape of ['line','area']){
  e.add('light.a',shape);e.pointerDown(evt(10,10));if(shape==='area'){e.pointerMove(evt(20,14));await e.pointerUp(evt(20,14));}else{await e.pointerUp(evt(10,10));e.pointerDown(evt(20,14));await e.pointerUp(evt(20,14));}
  await fire(document,'keydown',{key:'Enter'});const f=s.sent.at(-1).fixture;assert.equal(f.ref,'floor');assert.equal(f.building,'b');assert.equal(f.level,'L1');
  const p=f.at||f.path[0];assert.ok(Math.abs(p[2]-(4+1/12))<.00051);s.plan.light_fixtures['light.a']=[{...f,id:fid}];e.refresh();s.view.groups={levels:{'b:L1':{visible:false}}};e.draw();assert.equal(s.view.scene.getObjectByName('editor-light-fixtures').children.find(c=>c.userData.fixtureId).visible,false);
 }s.signal.abort();
});

function boxPick(s,centre,size,id='occluder'){
 const mesh=new THREE.Mesh(new THREE.BoxGeometry(...size),new THREE.MeshBasicMaterial());mesh.position.copy(centre);mesh.updateMatrixWorld(true);
 s.view.pick=(x,y)=>{const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(x/720-1,1-y/450),s.view.camera);const h=ray.intersectObject(mesh)[0];return h&&{kind:'wall',id,pieceId:id,building:'b',point:h.point.toArray()};};
 return ()=>{mesh.geometry.dispose();mesh.material.dispose();};
}
const nearPath=(a,b)=>{assert.equal(a.length,b.length);a.forEach((p,i)=>p.forEach((v,k)=>assert.ok(Math.abs(v-b[i][k])<1e-8,JSON.stringify({a,b}))));};
await test('keep_as_drawn_only_detached_and_preserves_live_path_with_foundation_lift',async()=>{
 const {resolveEmitters}=await import(file('static/twin/live/emitters.js'));
 const {buildingGround}=await import(file('static/twin/twin_ground.js'));
 for(const hostPresent of [true,false])for(const storedLift of (hostPresent?[0]:[0,1.5]))for(const facing of ['up','down','out','in']){
  const s=setup(),b=s.plan.buildings[0];b.foundation={mode:'auto',offset_ft:1.5};assert.ok(buildingGround(s.plan,b)>1);
  const f={...line,path:[[40,40,9+storedLift],[40,50,9+storedLift]],facing,snap:{host:{kind:'wall',id:hostPresent?'w':'gone'},edge:{from:[40,40],to:[40,50]},t0:0,t1:1}};
  s.plan.light_fixtures['light.a']=[f];
  f.detached=true;const before=resolveEmitters(s.plan,{},s.plan)[0].path;await click(byText(await card(s),'Keep as drawn'));assert.equal(s.sent.length,1);
  keepChecks.push({plan:structuredClone(s.plan),id:f.id,change:s.sent[0].change});const after={...f,...s.sent[0].change};s.plan.light_fixtures['light.a']=[after];assert.equal(after.snap,null);nearPath(before,resolveEmitters(s.plan,{},s.plan)[0].path);
 }
});
await test('attached_run_does_not_offer_keep_as_drawn',async()=>{const s=setup();s.plan.light_fixtures['light.a']=[{...line,snap:{host:{kind:'wall',id:'w'},edge:{from:[40,40],to:[40,50]},t0:0,t1:1}}];assert.equal(byText(await card(s),'Keep as drawn'),undefined);});
await test('snap_hover_and_click_reject_nearer_occluder_but_allow_own_proxy',async()=>{
 const {snapEdges}=await import(file('static/twin/editor/line_fixture_tool.js'));
 for(const blocked of [true,false]){
  const s=setup(),edge=snapEdges(s.plan).find(e=>e.host.kind==='wall'),p=edge.a.map((v,i)=>(v+edge.b[i])/2),target=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048);
  const toward=s.view.camera.position.clone().sub(target).normalize(),dispose=boxPick(s,target.clone().addScaledVector(toward,blocked?1:.1),[.08,.08,.08],blocked?'other-wall':'w');
  const e=await editor(s);e.add('light.a','line');await click(byText(document.getElementById('device-tools'),'Snap to edge'));const event=project(s,p);assert.ok(s.view.pick(event.clientX,event.clientY));e.pointerMove(event);
  const preview=s.view.scene.getObjectByName('editor-light-fixtures').children.find(c=>!c.userData.fixtureId);assert.equal(preview.children.length>0,!blocked);
  e.pointerDown(event);await e.pointerUp(event);assert.equal(s.sent.length,blocked?0:1);dispose();s.signal.abort();
 }
});
for(const shape of ['line','area','point','spot'])await test('wall_proxy_does_not_steal_'+shape+'_presses',async()=>{
  const s=setup(),z=4,y=10-.25-1/12;
  const f=shape==='line'?{...line,path:[[10,y,z],[20,y,z]]}:shape==='area'?{id:fid,shape,ref:'absolute',at:[15,y,z],size_ft:[10,4],facing:[0,-1,0]}:{id:fid,shape,ref:'absolute',at:[15,y,z],...(shape==='spot'?{aim:[15,0,z]}:{})};
  s.plan.light_fixtures['light.a']=[f];s.view.camera.position.set(15*.3048,z*.3048,5);s.view.camera.lookAt(15*.3048,z*.3048,-10*.3048);s.view.camera.updateMatrixWorld(true);
  const dispose=boxPick(s,new THREE.Vector3(15*.3048,4*.3048,-10*.3048),[10*.3048,9*.3048,.5*.3048+.2]);
  const e=await editor(s);e.refresh();const target=shape==='area'?[15,y,z+2]:[15,y,z+(['point','spot'].includes(shape)?.105/.3048:0)],event=project(s,target);
  assert.ok(s.view.pick(event.clientX,event.clientY));assert.equal(e.pointerDown(event),true,shape);await e.pointerUp(event);assert.ok(document.getElementById('piece-card').querySelector(`[data-fixture-id="${fid}"]`).open);dispose();s.signal.abort();
});
for(const shape of ['line','area'])await test('done_saves_pending_'+shape+'_and_failure_retains_draft',async()=>{
 const s=setup();s.plan.site.terraces=[];const send=s.op;let fail=true;s.op=o=>{if(fail)throw Error('offline');return send(o);};const e=await editor(s);e.add('light.a',shape);
 e.pointerDown(evt(10,10));await e.pointerUp(evt(10,10));e.pointerDown(evt(20,10));if(shape==='area')e.pointerMove(evt(24,14));await e.pointerUp(shape==='area'?evt(24,14):evt(20,10));
 await click(document.getElementById('device-cancel'));assert.equal(e.active(),true);assert.equal(s.sent.length,0);assert.ok(s.errors.some(x=>x.includes('offline')));
 fail=false;await click(document.getElementById('device-cancel'));assert.equal(s.sent.length,1);assert.equal(s.sent[0].fixture.shape,shape);assert.equal(e.active(),false);s.signal.abort();
});
await test('done_drops_unsaveable_single_point',async()=>{
 const s=setup(),e=await editor(s);e.add('light.a','line');e.pointerDown(evt(10));await e.pointerUp(evt(10));await click(document.getElementById('device-cancel'));assert.equal(e.active(),false);assert.equal(s.sent.length,0);assert.equal(s.errors.length,0);s.signal.abort();
});
for(const shape of ['line','area'])for(const surface of ['ground','floor','ceiling','wall'])await test('surface_default_facing_'+shape+'_'+surface,async()=>{
 for(const chosen of [false,true]){
  const s=setup();s.plan.site.terraces=[];const b=s.plan.buildings[0];b.rotation=0;b.position=[0,0];
  if(surface!=='ground')s.library.surfaceAt=ev=>({building:b,point:surface==='wall'?[ev.clientX,0,ev.clientY]:[ev.clientX,ev.clientY,surface==='ceiling'?9:0],level:'L1',kind:surface==='wall'?'wall':'room',piece:b.walls[0],side:'left',surface});
  const e=await editor(s);e.add('light.a',shape);const preset=surface==='wall'?'out':surface==='ceiling'?'up':'down';if(chosen){const f=document.getElementById('device-tools').querySelector('[aria-label="Facing"]');f.value=preset;await fire(f,'change');}
  e.pointerDown(evt(2,2));if(shape==='line'){await e.pointerUp(evt(2,2));e.pointerDown(evt(8,6));}else e.pointerMove(evt(8,6));await e.pointerUp(evt(8,6));await click(byText(document.getElementById('device-tools'),'Finish'));
  const f=s.sent[0]?.fixture;assert.ok(f,JSON.stringify(s.errors));const expected=chosen?preset:surface==='wall'?(shape==='area'?[0,1,0]:'in'):surface==='ceiling'?'down':'up';if(Array.isArray(expected))f.facing.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-8));else assert.equal(f.facing,expected);s.signal.abort();
 }
});
await test('clicked_face_ground_floor_ceiling_uses_surface_normal',async()=>{
 for(const surface of ['ground','floor','ceiling']){
  const s=setup();s.plan.site.terraces=[];const b=s.plan.buildings[0];if(surface!=='ground')s.library.surfaceAt=ev=>({building:b,point:[ev.clientX,ev.clientY,surface==='ceiling'?9:0],level:'L1',kind:'room',surface});
  const e=await editor(s);e.add('light.a','area');const f=document.getElementById('device-tools').querySelector('[aria-label="Facing"]');f.value='surface';await fire(f,'change');
  e.pointerDown(evt(2,2));e.pointerMove(evt(8,6));await e.pointerUp(evt(8,6));await click(byText(document.getElementById('device-tools'),'Finish'));assert.deepEqual(s.sent[0].fixture.facing,[0,0,surface==='ceiling'?-1:1]);s.signal.abort();
 }
});
await test('custom_area_normal_starts_at_current_preset_or_normal',async()=>{
 for(const [facing,normal]of [['up',[0,0,1]],['out',[0,-1,0]],['down',[0,0,-1]],[[.6,0,.8],[.6,0,.8]]]){
  const s=setup();s.plan.light_fixtures['light.a']=[{id:fid,shape:'area',ref:'absolute',at:[10,10,2],size_ft:[4,3],facing}];const n=await card(s),f=n.querySelector('[aria-label="Facing"]');f.value='normal';await fire(f,'change');assert.deepEqual(s.sent[0].change.facing,normal);
 }
});
await test('enter_on_buttons_and_links_keeps_native_activation_and_snap_hides_finish',async()=>{
 const s=setup(),e=await editor(s);e.add('light.a','line');for(const x of [2,8]){e.pointerDown(evt(x));await e.pointerUp(evt(x));}
 for(const target of [byText(document.getElementById('device-tools'),'Snap to edge'),document.getElementById('device-cancel'),document.createElement('a')]){
  const event=await fire(document,'keydown',{key:'Enter',target});assert.equal(event.defaultPrevented,false);assert.equal(s.sent.length,0);assert.equal(e.active(),true);
 }
 await click(byText(document.getElementById('device-tools'),'Snap to edge'));const finish=byText(document.getElementById('device-tools'),'Finish');assert.ok(!finish||finish.hidden||finish.disabled);s.signal.abort();
});
await test('pointercancel_cancels_only_current_click',async()=>{
 const s=setup();s.plan.site.terraces=[];const e=await editor(s);e.add('light.a','line');for(const x of [2,8]){e.pointerDown(evt(x));await e.pointerUp(evt(x));}
 e.pointerDown(evt(12));await e.pointerUp(evt(12),true);assert.equal(s.view.controls.enabled,true);await fire(document,'keydown',{key:'Enter'});assert.deepEqual(s.sent[0].fixture.path,[[2,10,0],[8,10,0]]);s.signal.abort();
});
await test('reversed_snap_drag_and_path_hardscape_match_server',async()=>{
 const s=setup();s.plan.site.hardscape=[{id:'path',kind:'path',points:[[60,10],[70,10],[75,15]],width:4,elevation:1}];const e=await editor(s),{snapEdges}=await import(file('static/twin/editor/line_fixture_tool.js'));const edge=snapEdges(s.plan).find(v=>v.host.kind==='hardscape');assert.ok(edge);
 e.add('light.a','line');await click(byText(document.getElementById('device-tools'),'Snap to edge'));const at=t=>edge.a.map((v,i)=>v+(edge.b[i]-v)*t);e.pointerDown(project(s,at(.8)));e.pointerMove(project(s,at(.2)));await e.pointerUp(project(s,at(.2)));const value=s.sent[0].fixture;assert.ok(value.snap.t0>value.snap.t1);assert.equal(value.snap.host.id,'path');snapChecks.push({plan:s.plan,value});s.signal.abort();
});
await test('jointless_wall_is_not_snap_candidate',async()=>{
 const s=setup();delete s.plan.buildings[0].walls[0].joints;const {snapEdges}=await import(file('static/twin/editor/line_fixture_tool.js'));assert.equal(snapEdges(s.plan).some(e=>e.host.kind==='wall'),false);
});
await test('detached_summary_and_reason_and_legacy_step_facing_are_truthful',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[{...line,detached:true,orphaned:true,orphan_reason:'The run would leave the lot.',snap:{host:{kind:'step',id:'s'},edge:{from:[0,0],to:[10,0]},t0:0,t1:1}}];const n=await card(s);assert.ok(textOf(n.querySelector('summary')).includes('detached'));assert.ok(textOf(n).includes('The run would leave the lot.'));
 const f=n.querySelector('[aria-label="Facing"]');assert.equal(f.value,'down');assert.ok(f.children.find(c=>c.value==='down').disabled);f.value='out';await fire(f,'change');assert.deepEqual(s.sent[0].change,{facing:'out'});delete s.plan.light_fixtures['light.a'][0].orphan_reason;const neutral=await card(s);assert.ok(textOf(neutral).includes('this run no longer follows its edge.'));assert.ok(!textOf(neutral).includes('host edge is missing'));
});


await test('snap_edges_cached_per_mode_and_invalidate_on_plan_change',async()=>{
 const s=setup(),walls=s.plan.buildings[0].walls;let enumerations=0;const iterator=walls[Symbol.iterator];walls[Symbol.iterator]=function*(){enumerations++;yield* iterator.call(this);};
 const e=await editor(s);e.add('light.a','line');await click(byText(document.getElementById('device-tools'),'Snap to edge'));const built=enumerations;assert.ok(built>0);
 for(let i=0;i<5;i++)e.pointerMove(evt(i));assert.equal(enumerations,built);
 walls[0].height=10;e.pointerMove(evt(3));assert.ok(enumerations>built);const rebuilt=enumerations;e.pointerMove(evt(4));assert.equal(enumerations,rebuilt);s.signal.abort();
});
await test('tube_markers_and_previews_reuse_dot_accent_and_dispose_on_redraw',async()=>{
 const s=setup();s.plan.light_fixtures['light.a']=[line,{id:'dot',shape:'point',ref:'absolute',at:[10,10,2]}];const e=await editor(s);e.refresh();const root=s.view.scene.getObjectByName('editor-light-fixtures'),marker=root.children.find(c=>c.userData.fixtureId===fid),dot=root.children.find(c=>c.userData.fixtureId==='dot');
 assert.equal(marker.material.color.getHex(),dot.material.color.getHex());assert.equal(marker.material.depthTest,true);let geometry=0,material=0;marker.geometry.addEventListener('dispose',()=>geometry++);marker.material.addEventListener('dispose',()=>material++);
 s.plan.light_fixtures['light.a'][0]={...line,path:[[10,10,2],[25,10,2]]};e.refresh();assert.equal(geometry,1);assert.equal(material,1);
 e.add('light.a','line');for(const x of [2,8]){e.pointerDown(evt(x));await e.pointerUp(evt(x));}const preview=root.children.find(c=>!c.userData.fixtureId),stroke=preview.children[0];assert.equal(stroke.isMesh,true);assert.equal(stroke.material.color.getHex(),dot.material.color.getHex());
 let disposed=0;stroke.geometry.addEventListener('dispose',()=>disposed++);e.pointerMove(evt(12));assert.equal(disposed,1);const current=preview.children[0];let stopped=0;current.material.addEventListener('dispose',()=>stopped++);e.cancel();assert.equal(stopped,1);s.signal.abort();
});
for(const kind of ['wall','step'])await test(kind+'_top_marker_tolerates_proxy_but_yields_to_nearer_piece',async()=>{
 const {snapEdges}=await import(file('static/twin/editor/line_fixture_tool.js'));
 const s=setup(),edge=snapEdges(s.plan).find(e=>e.host.kind===kind),f={...line,path:[edge.a,edge.b],facing:'out',snap:{host:edge.host,edge:{from:edge.a.slice(0,2),to:edge.b.slice(0,2)},t0:0,t1:1}};s.plan.light_fixtures['light.a']=[f];
 const p=edge.a.map((v,i)=>(v+edge.b[i])/2),target=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048),toward=s.view.camera.position.clone().sub(target).normalize();const e=await editor(s);e.refresh();
 for(const gap of [.1,.8]){const dispose=boxPick(s,target.clone().addScaledVector(toward,gap),[.02,.02,.02]);const event=project(s,p);assert.ok(s.view.pick(event.clientX,event.clientY));assert.equal(e.pointerDown(event),gap<.2);if(gap<.2)await e.pointerUp(event);dispose();}s.signal.abort();
});

console.log('SNAP_CHECKS '+JSON.stringify(snapChecks));
console.log('KEEP_CHECKS '+JSON.stringify(keepChecks));
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    lines = output.splitlines()
    print('\n'.join(line for line in lines if not line.startswith(('SNAP_CHECKS ', 'KEEP_CHECKS '))))
    if code == 0:
        sys.path.insert(0, str(ROOT))
        from services.twin_fixtures import resolve_snap, apply_op
        checks = json.loads(next(line[12:] for line in lines if line.startswith('SNAP_CHECKS ')))
        for check in checks:
            plan, value = check['plan'], check['value']
            expected = resolve_snap(plan, value['snap'])
            assert expected is not None
            assert all(abs(a-b) < 1e-8 for p, q in zip(expected, value['path']) for a, b in zip(p, q)), check
            plan['light_fixtures'] = {}
            apply_op(plan, {'op': 'add_light_fixture', 'entity_id': 'light.a', 'fixture': value})
            assert plan['light_fixtures']['light.a'][0]['path'] == expected
            stored = plan['light_fixtures']['light.a'][0]
            apply_op(plan, {'op': 'update_light_fixture', 'entity_id': 'light.a', 'id': stored['id'], 'change': {'snap': None}})
            drawn = plan['light_fixtures']['light.a'][0]
            assert 'snap' not in drawn and not drawn['detached'] and drawn['id'] == stored['id'] and drawn['path'] == expected
        kept = json.loads(next(line[12:] for line in lines if line.startswith('KEEP_CHECKS ')))
        for check in kept:
            plan = check['plan']
            apply_op(plan, {'op': 'update_light_fixture', 'entity_id': 'light.a', 'id': check['id'], 'change': check['change']})
            drawn = plan['light_fixtures']['light.a'][0]
            assert 'snap' not in drawn and not drawn['detached'] and drawn['ref'] == 'absolute'
            assert drawn['path'] == check['change']['path'] and drawn['id'] == check['id']
        print(f'  ok   Editor Keep as drawn payloads accepted by real server: {len(kept)}/{len(kept)}')
        print(f'  ok   JS snap paths accepted by real server ops: {len(checks)}/{len(checks)}')
        print(f'  ok   Keep as drawn accepted by existing server update op: {len(checks)}/{len(checks)}')
    sys.exit(code if code is not None else 1)
