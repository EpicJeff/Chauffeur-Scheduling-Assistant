"""Task 5: run the real fixture card, placement and shared aim tool in node."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const modules=async()=>await import(file('static/twin/editor/fixtures.js'));
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
const evt=(x,y=10)=>({clientX:x,clientY:y,button:0,pointerId:1});
const fixture={id:'fixture:00000000-0000-4000-8000-000000000001',shape:'spot',ref:'absolute',at:[10,10,6],aim:[20,10,0],cone_deg:90,softness:.3};
function setup(){
 const plan={buildings:[],site:{lot:[[0,0],[100,0],[100,100],[0,100]]},light_fixtures:{'light.a':[structuredClone(fixture)]}};
 const sent=[],errors=[],canvas=document.createElement('canvas'),view={scene:new THREE.Group(),renderer3:{domElement:canvas},controls:{enabled:true},camera:new THREE.PerspectiveCamera(),pick:()=>null};
 document.body.append(canvas);const bar=document.getElementById('device-tools');bar.replaceChildren();const done=document.createElement('button');done.id='device-cancel';bar.append(document.getElementById('device-note'),done);const signal=new AbortController();let editable=true;
 const library={surfaceAt:()=>null,ground:e=>[e.clientX,e.clientY]};
 return {plan,sent,errors,view,library,signal,canEdit:()=>editable,lock:()=>editable=false,
  op:async o=>{sent.push(o);},getPlan:()=>plan,prepare(){},tools:{setTool(){},select(){},selection:()=>({}),haLink:{state:()=>({devices:[]})}}};
}
const THREE=await import('three');
await test('multi_drop_posts_one_op_per_click',async()=>{
 const {createFixtureEditor}=await modules(),s=setup(),editor=createFixtureEditor({...s,signal:s.signal.signal,report:e=>s.errors.push(e)});
 editor.add('light.a','point');for(const x of [10,20,30]){assert.equal(editor.pointerDown(evt(x)),true);await editor.pointerUp(evt(x));}
 assert.deepEqual(s.sent.map(o=>o.op),['add_light_fixture','add_light_fixture','add_light_fixture']);
 assert.deepEqual(s.sent.map(o=>o.fixture.at),[[10,10,0],[20,10,0],[30,10,0]]);
 await click(byText(document.getElementById('device-tools'),'Done'));assert.equal(editor.pointerDown(evt(40)),false);
 assert.equal(s.view.controls.enabled,true);s.signal.abort();assert.deepEqual(s.errors,[]);
});
await test('refresh_before_any_house_exists',async()=>{
 // A household that has not built a house yet has no plan; the editor must still open.
 const {createFixtureEditor}=await modules(),s=setup();let plan=null;
 const editor=createFixtureEditor({...s,getPlan:()=>plan,signal:s.signal.signal,report:e=>s.errors.push(e)});
 editor.refresh();plan=s.plan;editor.refresh();
 assert.ok(s.view.scene.children.length>0);s.signal.abort();assert.deepEqual(s.errors,[]);
});
await test('aim_drag_commits_once_with_cone',async()=>{
 const {aimTool}=await import(file('static/twin/editor/aim_tool.js'));const commits=[],s=setup();
 const tool=aimTool({at:fixture.at,aim:fixture.aim,cone_deg:90,onCommit:v=>commits.push(v)});
 tool.begin();tool.move([25,10,0]);tool.move([30,10,0]);tool.cone(60);assert.equal(commits.length,0);
 await tool.end();await tool.end();assert.deepEqual(commits,[{aim:[30,10,0],cone_deg:60}]);
 assert.ok(tool.preview.children.length);tool.begin();tool.move([40,10,0]);await tool.end(true);assert.equal(commits.length,1);tool.stop();
});
await test('camera_facing_maps_to_aim',async()=>{
 const {cameraView}=await modules();const m={entity_id:'camera.a',at:[2,3,5],facing_deg:90};
 const v=cameraView({},m);assert.equal(v.fov_deg,90);assert.ok(Math.abs(v.aim[0]-2)<1e-8);assert.deepEqual(v.aim.slice(1),[23,5]);
 const saved={at:[1,2,3],aim:[4,5,0],fov_deg:70};assert.deepEqual(cameraView({camera_views:{'camera.a':saved}},m),{...saved,at:m.at});
 const s=setup(),{createFixtureEditor}=await modules();const e=createFixtureEditor({...s,signal:s.signal.signal});
 e.aimCamera(m);e.pointerDown(evt(10));e.pointerMove(evt(20));await e.pointerUp(evt(20));
 assert.equal(s.sent.length,1);assert.equal(s.sent[0].op,'set_camera_view');assert.equal(s.sent[0].entity_id,'camera.a');s.signal.abort();
});
await test('rows_edit_duplicate_delete_no_browser_dialogs',async()=>{
 for(const name of ['alert','confirm','prompt'])window[name]=()=>{throw Error('browser dialog');};
 const {fixtureCard}=await modules(),s=setup(),confirms=[];window.promptConfirm=async(...args)=>{confirms.push(args);return true;};
 const node=fixtureCard({entity_id:'light.a',getPlan:s.getPlan,canEdit:s.canEdit,op:s.op});document.body.append(node);
 const share=node.querySelector('[aria-label="Share"]');share.value='2';await fire(share,'change');
 assert.deepEqual(s.sent[0],{op:'update_light_fixture',entity_id:'light.a',id:fixture.id,change:{share:2}});
 share.value='';await fire(share,'change');assert.deepEqual(s.sent.at(-1).change,{share:null});
 const softness=node.querySelector('[aria-label="Softness"]');softness.value='.7';await fire(softness,'change');assert.equal(s.sent.at(-1).change.softness,.7);
 await click(byText(node,'Duplicate'));assert.equal(s.sent.at(-1).op,'add_light_fixture');assert.equal(s.sent.at(-1).fixture.id,undefined);
 await click(byText(node,'Delete'));assert.equal(confirms.length,1);assert.equal(s.sent.at(-1).op,'delete_light_fixture');
 const output=node.querySelector('[aria-label="Output (lm)"]');output.value='1200';await fire(output,'change');assert.equal(s.sent.at(-1).output_lm,1200);
});
await test('read_only_for_non_parents',async()=>{
 const {fixtureCard,createFixtureEditor}=await modules(),s=setup();s.lock();
 const node=fixtureCard({entity_id:'light.a',getPlan:s.getPlan,canEdit:s.canEdit,op:s.op});
 assert.ok(textOf(node).includes('Spot'));assert.ok(node.querySelectorAll('input,select,button').every(n=>n.disabled));
 for(const n of node.querySelectorAll('input')){n.value='4';await fire(n,'change');}
 const e=createFixtureEditor({...s,signal:s.signal.signal});e.add('light.a','point');assert.equal(e.pointerDown(evt(10)),false);assert.deepEqual(s.sent,[]);s.signal.abort();
});
await test('real_device_card_wiring_and_line_controls',async()=>{
 const {createHaLink}=await import(file('static/twin/editor/ha_link.js'));
 const {createDevicePlacement}=await import(file('static/twin/editor/device_placement.js'));
 const s=setup(),device={device_id:'d',entity_id:'light.a',entities:['light.a','switch.b'],name:'Garden lights',kind:'light',area_id:'garden'};
 s.plan.site.yard_rooms=[{id:'yard',ha_area:'garden',polygon:[[0,0],[90,0],[90,90],[0,90]]}];
 s.plan.light_fixtures['light.a'].push({id:'fixture:line',shape:'line',ref:'absolute',path:[[0,0,1],[10,0,1]],facing:'out',width_in:.5,share:2,
  snap:{host:{kind:'wall',id:'w'},edge:{from:[0,0],to:[10,0]},t0:0,t1:1}});
 const link=createHaLink({api:{request:async()=>({available:true,areas:[{area_id:'garden',name:'Garden'}],rooms:[{room:'yard',building:null,ha_area:'garden'}],devices:[device]}),report:e=>{throw e;}},
  onCommit:s.op,signal:s.signal.signal,getPlan:s.getPlan,canEdit:s.canEdit});s.tools.haLink=link;await link.refresh();
 const placement=createDevicePlacement({...s,signal:s.signal.signal});
 const host=document.createElement('div'),record={kind:'yard_rooms',piece:s.plan.site.yard_rooms[0],building:null};link.draw(host,record);
 await click(byText(host,'Fixtures'));const card=document.getElementById('piece-card');assert.equal(card.querySelectorAll('[data-fixture-entity]').length,2);
 const line=card.querySelector('[data-fixture-id="fixture:line"]');assert.equal(line.querySelector('[aria-label="Share"]').disabled,false);
 for(const name of ['Redraw','Duplicate','Delete','Pick another edge'])assert.ok(byText(line,name));
 await click(byText(card,'Add point fixtures'));assert.equal(document.getElementById('device-tools').hidden,false);
 placement.pointerDown(evt(12));await placement.pointerUp(evt(12));assert.equal(s.sent.at(-1).op,'add_light_fixture');
 placement.cancel();s.lock();link.draw(host,record);await click(byText(host,'Fixtures'));assert.ok(card.querySelectorAll('input,select').every(n=>n.disabled));
 assert.ok(card.querySelectorAll('button').filter(n=>textOf(n)!=='Close').every(n=>n.disabled));
 s.signal.abort();
});
await test('floor_drop_move_and_wall_aim_keep_raw_lot_coordinates',async()=>{
 const {createFixtureEditor}=await modules(),s=setup();
 const building={id:'b',rotation:90,position:[20,30],base:2,levels:[{id:'L1',elevation:9,ceiling:9}],rooms:[],walls:[]};s.plan.buildings=[building];
 s.library.surfaceAt=()=>({building,point:[2,3,15],level:'L1',kind:'wall'});
 const e=createFixtureEditor({...s,signal:s.signal.signal});e.add('light.a','spot');e.pointerDown(evt(10));await e.pointerUp(evt(10));
 const f=s.sent[0].fixture;assert.ok(Math.abs(f.at[0]-17)<1e-8);assert.equal(f.at[1],32);assert.equal(f.at[2],6);assert.equal(f.ref,'floor');
 const saved={...f,id:fixture.id};s.library.surfaceAt=()=>({building,point:[5,3,15],level:'L1',kind:'wall'});e.aim('light.a',saved);e.pointerDown(evt(10));e.pointerMove(evt(20));await e.pointerUp(evt(20));
 assert.equal(s.sent[1].change.aim[2],6);assert.equal(s.sent[1].change.cone_deg,90);
 e.move('light.a',saved);s.library.surfaceAt=()=>null;e.pointerDown(evt(40));await e.pointerUp(evt(40));
 assert.deepEqual(s.sent.at(-1).change.at,[40,10,0]);assert.equal(s.sent.at(-1).change.ref,'ground');s.signal.abort();
});
await test('cancelled_drag_failed_save_and_slider_are_single_edits',async()=>{
 const {createFixtureEditor}=await modules(),s=setup(),e=createFixtureEditor({...s,signal:s.signal.signal});
 e.aim('light.a',fixture);e.pointerDown(evt(10));e.pointerMove(evt(20));await e.pointerUp(evt(20),true);assert.equal(s.sent.length,0);
 const slider=document.getElementById('device-tools').querySelector('input[type="range"]');slider.value='55';await fire(slider,'input');assert.equal(s.sent.length,0);
 await fire(slider,'change');assert.equal(s.sent.length,1);assert.equal(s.sent[0].change.cone_deg,55);
 s.lock();e.pointerDown(evt(10));await e.pointerUp(evt(20));assert.equal(s.sent.length,1);e.refresh();assert.equal(s.view.controls.enabled,true);s.signal.abort();
 const {aimTool}=await import(file('static/twin/editor/aim_tool.js'));const tool=aimTool({at:fixture.at,aim:fixture.aim,onCommit:async()=>{throw Error('failed');}});
 tool.begin();tool.move([30,30,0]);await assert.rejects(tool.end(),/failed/);await tool.commit();tool.stop();
});
await test('scene_fixture_selection_opens_its_row_and_survives_card_refresh',async()=>{
 const {createFixtureEditor}=await modules(),{createCards}=await import(file('static/twin/editor/cards.js')),s=setup();
 const target=new THREE.Vector3(10*.3048,6*.3048,-10*.3048);s.view.camera.position.copy(target).add(new THREE.Vector3(0,2,5));s.view.camera.aspect=1440/900;s.view.camera.updateProjectionMatrix();s.view.camera.lookAt(target);s.view.camera.updateMatrixWorld(true);
 const e=createFixtureEditor({...s,signal:s.signal.signal});e.refresh();assert.equal(e.pointerDown(evt(720,450)),true);await e.pointerUp(evt(720,450));
 const host=document.getElementById('piece-card'),row=host.querySelector(`[data-fixture-id="${fixture.id}"]`);assert.ok(row.open);
 const cards=createCards({getPlan:s.getPlan,getLabel:()=>'',getKit:()=>({}),canEdit:s.canEdit,op:s.op,select(){},edit(){},ask(){}});cards.draw(null);assert.equal(host.hidden,false);assert.ok(row.open);s.signal.abort();delete host.dataset.fixtureCard;
});
await test('saved_camera_frustum_uses_shared_cone_and_invalidates_live_layout',async()=>{
 const {mountSecurity}=await import(file('static/twin/live/security.js')),{layoutKey}=await import(file('static/twin/live/live.js'));
 const s=setup(),camera={at:[10,10,6],aim:[25,15,0],fov_deg:65},marker={kind:'camera',device_id:'cam',entity_id:'camera.a',at:[10,10,6],building:null};
 const layout={markers:[marker],rooms:[],camera_views:{'camera.a':camera}};s.view.plan=s.plan;
 const live={layout:()=>layout,stale:()=>false,state:()=>({state:'idle'}),peek:()=>({})};
 const layer=mountSecurity({view:s.view,live});layer.update('security');let cone;s.view.scene.traverse(o=>{if(o.userData.cameraCone)cone=o;});
 assert.ok(cone.visible);assert.equal(cone.userData.cameraCone.fov_deg,65);assert.equal(cone.children[0].isLineSegments,true);
 const before=layoutKey(layout,s.plan);camera.aim=[30,20,0];assert.notEqual(layoutKey(layout,s.plan),before);layer.stop();s.signal.abort();
});

await test('camera_view_origin_follows_replacement_in_editor_and_viewer',async()=>{
 const {createFixtureEditor,cameraView}=await modules(),{mountSecurity}=await import(file('static/twin/live/security.js')),s=setup();
 const marker={kind:'camera',device_id:'cam',entity_id:'camera.a',at:[10,10,6],building:null};
 const editor=createFixtureEditor({...s,signal:s.signal.signal});editor.aimCamera(marker);editor.pointerDown(evt(10));await editor.pointerUp(evt(30));
 const saved=s.sent[0].view;s.plan.camera_views={'camera.a':saved};marker.at=[40,20,8];
 assert.deepEqual(cameraView(s.plan,marker),{at:marker.at,aim:saved.aim,fov_deg:saved.fov_deg});
 const legacy={...saved,at:[1,2,3]},layout={markers:[marker],rooms:[],camera_views:{'camera.a':legacy}};s.view.plan=s.plan;
 const layer=mountSecurity({view:s.view,live:{layout:()=>layout,stale:()=>false,state:()=>({state:'idle'}),peek:()=>({})}});
 const cone=layer.warmObjects().find(o=>o.userData.cameraCone),positions=cone.children[0].geometry.attributes.position;
 const origin=new THREE.Vector3(marker.at[0]*.3048,marker.at[2]*.3048,-marker.at[1]*.3048);
 assert.ok(Array.from({length:positions.count},(_,i)=>new THREE.Vector3().fromBufferAttribute(positions,i)).some(p=>p.distanceTo(origin)<1e-6));
 assert.equal(layer.legend().includes('25 ft'),false);assert.equal('at' in saved,false);layer.stop();s.signal.abort();
});
await test('real_surface_hits_store_fixture_outside_clicked_wall_face_and_slabs',async()=>{
 const {createFixtureEditor}=await modules(),{createLibrary}=await import(file('static/twin/editor/library.js')),s=setup();
 const wall={id:'wall',level:'L1',from:[0,0],to:[20,0],thickness:.5},room={id:'room',level:'L1',polygon:[[0,0],[20,0],[20,20],[0,20]]};
 const building={id:'b',position:[0,0],rotation:0,base:0,levels:[{id:'L1',elevation:0,ceiling:9}],rooms:[room],walls:[wall],roof:{sections:[]}};
 s.plan.buildings=[building];s.view.controls.addEventListener=()=>{};s.view.controls.removeEventListener=()=>{};
 s.view.pick=()=>({building:'b',kind:'wall',id:'wall'});
 s.library=createLibrary({...s,kit:{},signal:s.signal.signal});
 const editor=createFixtureEditor({...s,signal:s.signal.signal});
 function look(at,target){s.view.camera.position.set(at[0]*.3048,at[2]*.3048,-at[1]*.3048);s.view.camera.lookAt(target[0]*.3048,target[2]*.3048,-target[1]*.3048);s.view.camera.updateMatrixWorld(true);}
 for(const [side,y] of [['left',10],['right',-10]]){
  look([10,y,5],[10,0,5]);assert.equal(s.library.surfaceAt(evt(720,450)).side,side);
  editor.add('light.a','point');editor.pointerDown(evt(720,450));await editor.pointerUp(evt(720,450));
  assert.ok(Math.abs(s.sent.at(-1).fixture.at[1]-(side==='left'?1:-1)*(.25+1/12))<1e-6);
 }
 editor.move('light.a',fixture);editor.pointerDown(evt(720,450));await editor.pointerUp(evt(720,450));
 assert.ok(Math.abs(s.sent.at(-1).change.at[1]+.25+1/12)<1e-6);
 s.view.pick=()=>({building:'b',kind:'room',id:'room'});
 for(const [camera,target,z] of [[[10,10,6],[10,10,0],1/12],[[10,10,3],[10,10,9],9-1/12]]){
  look(camera,target);editor.add('light.a','spot');editor.pointerDown(evt(720,450));await editor.pointerUp(evt(720,450));
  const f=s.sent.at(-1).fixture;assert.ok(Math.abs(f.at[2]-z)<1e-6);
  if(z>1){assert.deepEqual(f.aim.slice(0,2),f.at.slice(0,2));assert.equal(f.aim[2],0);}
 }
 s.signal.abort();
});
await test('stair_draft_and_abort_release_fixture_card_ownership',async()=>{
 const {createFixtureEditor}=await modules(),{createDraw}=await import(file('static/twin/editor/draw.js')),{createCards}=await import(file('static/twin/editor/cards.js')),s=setup();
 const building={id:'b',levels:[{id:'L1',elevation:0,ceiling:9},{id:'L2',elevation:9,ceiling:9}],walls:[],rooms:[]};s.plan.buildings=[building];
 const cards=createCards({getPlan:s.getPlan,getLabel:()=>'',getKit:()=>({}),canEdit:s.canEdit,op:s.op,select(){},edit(){},ask(){}});
 s.tools.floor=()=>({building,level:building.levels[0],key:'b:L1'});s.tools.select=next=>cards.draw(next);
 const editor=createFixtureEditor({...s,signal:s.signal.signal}),draw=createDraw({...s,gesture:f=>f(),signal:s.signal.signal,panel:{message:assert.fail}});
 const host=document.getElementById('piece-card'),device={device_id:'d',entity_id:'light.a',name:'Lamp'};
 editor.showDevice(device);await click(document.getElementById('rail-add-stair'));
 assert.equal(host.dataset.fixtureCard,undefined);s.plan.light_fixtures_meta={'light.a':{output_lm:1000}};editor.refresh();assert.ok(textOf(host).includes('Add stair'));
 draw.cancel();cards.draw(null);editor.refresh();assert.equal(host.hidden,true);
 editor.showDevice(device);s.signal.abort();assert.equal(host.dataset.fixtureCard,undefined);cards.draw(null);assert.equal(host.hidden,true);
});


await test('escape_cancels_only_current_aim_drag_then_ends_idle_aim',async()=>{
 const {createFixtureEditor}=await modules(),s=setup(),e=createFixtureEditor({...s,signal:s.signal.signal});
 e.aim('light.a',fixture);e.pointerDown(evt(10));e.pointerMove(evt(20));await fire(document,'keydown',{key:'Escape'});
 assert.equal(e.active(),true);assert.equal(s.view.controls.enabled,true);assert.equal(s.sent.length,0);
 assert.equal(e.pointerUp(evt(20)),false);e.pointerDown(evt(10));await e.pointerUp(evt(30));assert.equal(s.sent.length,1);
 await fire(document,'keydown',{key:'Escape'});assert.equal(e.active(),false);s.signal.abort();
});
await test('fixture_markers_follow_floor_visibility_and_leave_front_piece_presses',async()=>{
 const {createFixtureEditor}=await modules(),s=setup();s.plan.buildings=[{id:'b',levels:[{id:'up',elevation:0}]}];
 Object.assign(s.plan.light_fixtures['light.a'][0],{ref:'floor',building:'b',level:'up'});s.view.groups={levels:{'b:up':{visible:true}}};
 const target=new THREE.Vector3(10*.3048,6*.3048,-10*.3048);s.view.camera.position.copy(target).add(new THREE.Vector3(0,2,5));s.view.camera.lookAt(target);s.view.camera.updateMatrixWorld(true);
 const editor=createFixtureEditor({...s,signal:s.signal.signal});editor.refresh();
 const mesh=s.view.scene.getObjectByName('editor-light-fixtures').children[0];assert.equal(mesh.visible,true);assert.equal(mesh.material.depthTest,true);
 s.view.groups.levels['b:up'].visible=false;editor.draw();assert.equal(mesh.visible,false);assert.equal(editor.pointerDown(evt(720,450)),false);
 s.view.groups.levels['b:up'].visible=true;editor.draw();assert.equal(mesh.visible,true);
 const front=new THREE.Mesh(new THREE.BoxGeometry(.5,.5,.5),new THREE.MeshBasicMaterial());front.position.copy(s.view.camera.position).lerp(target,.5);front.updateMatrixWorld(true);
 const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(0,0),s.view.camera);const hit=ray.intersectObject(front)[0];assert.ok(hit);
 s.view.pick=()=>({pieceId:'wall',point:hit.point.toArray()});assert.equal(editor.pointerDown(evt(720,450)),false);
 s.view.pick=()=>null;assert.equal(editor.pointerDown(evt(720,450)),true);await editor.pointerUp(evt(720,450),true);s.signal.abort();front.geometry.dispose();front.material.dispose();
});
await test('read_only_scene_press_passes_through_real_scene_tools_to_fixture_card',async()=>{
 const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js')),{createDevicePlacement}=await import(file('static/twin/editor/device_placement.js'));
 for(const reason of ['non-parent','history preview']){
  const s=setup();s.lock();s.view.state={view:'ext'};s.view.controls.addEventListener=()=>{};s.view.controls.removeEventListener=()=>{};
  const target=new THREE.Vector3(10*.3048,6*.3048,-10*.3048);s.view.camera.position.copy(target).add(new THREE.Vector3(0,2,5));s.view.camera.lookAt(target);s.view.camera.updateMatrixWorld(true);
  const tools=createSceneTools({...s,getModel:s.getPlan,getKit:()=>({}),getSheets:()=>({}),signal:s.signal.signal,panel:{clearSelection(){}},api:{request:async()=>({available:false}),report:assert.fail}});
  const placement=createDevicePlacement({...s,tools,signal:s.signal.signal});placement.refresh();
  tools.delegate({pointerBrowse:placement.pointerBrowse,pointerDown:assert.fail,pointerMove:placement.pointerMove,pointerUp:placement.pointerUp});
  await fire(s.view.renderer3.domElement,'pointerdown',evt(720,450));await fire(s.view.renderer3.domElement,'pointerup',evt(720,450));
  const host=document.getElementById('piece-card');assert.equal(host.hidden,false,reason);assert.ok(host.querySelector(`[data-fixture-id="${fixture.id}"]`).open,reason);
  assert.ok(host.querySelectorAll('input,select').every(n=>n.disabled));assert.ok(host.querySelectorAll('button').filter(n=>textOf(n)!=='Close').every(n=>n.disabled));assert.deepEqual(s.sent,[]);s.signal.abort();
 }
});


await test('placed_camera_reaim_uses_current_wall_marker_and_legacy_rotated_facing',async()=>{
 const {createDevicePlacement}=await import(file('static/twin/editor/device_placement.js')),s=setup();
 const b={id:'b',position:[20,30],rotation:90,base:2,levels:[{id:'L1',elevation:0,ceiling:9}],rooms:[],anchors:[],
  walls:[{id:'w1',from:[0,0],to:[20,0],level:'L1',thickness:.5},{id:'w2',from:[0,10],to:[20,10],level:'L1',thickness:.5}],
  devices:[{device:'cam',host:{wall:'w1',side:'left',at:5,z:6},offset:0,facing_deg:30}]};s.plan.buildings=[b];
 const device={device_id:'cam',entity_id:'camera.a',kind:'camera',name:'Camera',entities:['camera.a']};
 s.tools.haLink={state:()=>({devices:[device]}),setPlacement(){}};
 const placement=createDevicePlacement({...s,signal:s.signal.signal}),host=document.createElement('div');placement.drawFixtures(host,device);
 await click(byText(host,'Fixtures and camera view'));const card=document.getElementById('piece-card');await click(byText(card,'Aim camera'));
 let preview=s.view.scene.getObjectByName('editor-light-fixtures').children.find(c=>c.children.length),target=preview.children.find(c=>c.userData.aimHandle).position;
 const initial=[19.75,35,8],angle=120*Math.PI/180;
 assert.ok(Math.abs(target.x/.3048-(initial[0]+20*Math.cos(angle)))<1e-6);assert.ok(Math.abs(-target.z/.3048-(initial[1]+20*Math.sin(angle)))<1e-6);
 placement.pointerDown(evt(10));await placement.pointerUp(evt(30));s.plan.camera_views={'camera.a':s.sent.at(-1).view};
 const saved=structuredClone(s.plan.camera_views['camera.a']);b.devices[0].host={wall:'w2',side:'left',at:10,z:6};
 // The old card button must re-read the placement even before the next poll redraw.
 await click(byText(card,'Aim camera'));
 preview=s.view.scene.getObjectByName('editor-light-fixtures').children.find(c=>c.children.length);
 const positions=preview.children[0].children[0].geometry.attributes.position,origin=new THREE.Vector3(9.75*.3048,8*.3048,-40*.3048);
 assert.ok(Array.from({length:positions.count},(_,i)=>new THREE.Vector3().fromBufferAttribute(positions,i)).some(p=>p.distanceTo(origin)<1e-6));
 assert.deepEqual(s.plan.camera_views['camera.a'],saved);s.signal.abort();
});

finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code if code is not None else 1)
