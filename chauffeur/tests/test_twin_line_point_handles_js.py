"""Line point handles through the real fixture editor and scene arbiter (no browser)."""
import sys
import json
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE = await import('three');
const {createDevicePlacement} = await import(file('static/twin/editor/device_placement.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {resolveFixture} = await import(file('static/twin/live/emitters.js'));
const {HANDLE_HIT_PX} = await import(file('static/twin/editor/picking.js'));
const id='fixture:00000000-0000-4000-8000-000000000001';
const effectId='effect:00000000-0000-4000-8000-000000000001';
const line=()=>({id,shape:'line',ref:'absolute',path:[[10,10,3],[20,10,6],[30,10,9]],facing:'out',width_in:.5});
const event=(p,extra={})=>({clientX:p[0],clientY:p[1],button:0,pointerId:1,...extra});
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup({fixture=line(),effect=false,readonly=false}={}) {
 if(effect) delete fixture.width_in;
 const plan={buildings:[],site:{lot:[[0,0],[100,0],[100,100],[0,100]]},
   light_fixtures:effect?{}:{'light.a':[fixture]},effect_fixtures:effect?[fixture]:[]};
 const abort=new AbortController(),sent=[],errors=[],selections=[],controlStates=[];let writable=!readonly;
 const host=document.createElement('div'),canvas=document.createElement('canvas');document.body.append(host);host.append(canvas);
 const controls=new THREE.EventDispatcher();let enabled=true;
 Object.defineProperty(controls,'enabled',{get:()=>enabled,set:value=>{enabled=value;controlStates.push(value);}});
 const view={scene:new THREE.Group(),renderer3:{domElement:canvas},controls,state:{view:'ext'},groups:{levels:{}},
   camera:new THREE.PerspectiveCamera(60,1440/900,.01,1000),pick:()=>null,pickAll:()=>[],
   setSelection:s=>{selections.push(s.selected);return 0;}};
 view.camera.position.set(6,20,12);view.camera.lookAt(6,1.8,-3);view.camera.updateMatrixWorld(true);
 document.getElementById('piece-card').replaceChildren();
 const options={view,getPlan:()=>plan,op:async o=>sent.push(o),canEdit:()=>writable,signal:abort.signal};
 let devices;
 const tools=createSceneTools({...options,getModel:()=>plan,getKit:()=>({}),getSheets:()=>({}),edit:assert.fail,
   panel:{clearSelection(){},focusSelection(){}},fixtureHits:(x,y)=>devices?.fixtureHits(x,y)||[]});
 tools.haLink.state=()=>({available:false,devices:[]});
 const library={surfaceAt:()=>{throw Error('point handles must not pick the floor or wall');},ground:()=>null};
 devices=createDevicePlacement({...options,tools,library,prepare(){}});
 tools.delegate({handleSources:[devices.fixtureHandles],selectPick:hit=>devices.selectFixturePick?.(hit),
   pointerArmedDown:devices.pointerArmedDown,pointerDown:devices.pointerDown,pointerMove:devices.pointerMove,
   pointerUp:devices.pointerUp,pointerBrowse:devices.pointerBrowse});
 tools.setTool('select');devices.refresh();
 const project=p=>{view.camera.updateMatrixWorld(true);const v=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(view.camera);return [(v.x+1)*720,(1-v.y)*450];};
 const point=i=>project(resolveFixture(fixture,plan).path[i]);
 let orbitPresses=0;canvas.addEventListener('pointerdown',()=>orbitPresses++,{signal:abort.signal});
 const send=async(type,p,extra={})=>{await fire(canvas,type,event(p,extra));await settle();};
 const clickAt=async p=>{await send('pointerdown',p);await send('pointerup',p);};
 const choose=async()=>{await clickAt(point(1));assert.equal(document.getElementById('piece-card').dataset.fixtureCard,effect?fixture.id:'light.a');};
 return {plan,fixture,abort,sent,errors,selections,controlStates,view,tools,devices,options,library,project,point,send,clickAt,choose,
   handles:()=>devices.fixtureHandles.handles(),orbitPresses:()=>orbitPresses,lock:()=>{writable=false;},close:()=>{abort.abort();host.remove();}};
}
async function scenario(name,fn,options){await test(name,async()=>{const s=setup(options);try{await fn(s);}finally{s.close();}});}

await scenario('free_line_has_a_handle_per_point',async s=>{
 assert.equal(s.handles().length,0);await s.choose();const handles=s.handles();assert.equal(handles.length,3);
 for(let i=0;i<3;i++) {assert.equal(handles[i].index,i);handles[i].screen.forEach((v,k)=>near(v,s.point(i)[k]));}
 assert.equal(document.querySelectorAll('.editor-handle').filter(n=>n.dataset.fixturePoint!==undefined).length,3);
 const p=handles[0].screen;
 assert.ok(s.devices.fixtureHandles.hit(event([p[0]+HANDLE_HIT_PX,p[1]])));
 assert.equal(s.devices.fixtureHandles.hit(event([p[0]+HANDLE_HIT_PX+1,p[1]])),null);
 // Projection is refreshed after the camera moves, without waiting for a plan poll.
 s.view.camera.position.x+=2;s.view.camera.lookAt(6,1.8,-3);s.view.camera.updateMatrixWorld(true);
 s.view.controls.dispatchEvent({type:'change'});s.handles()[0].screen.forEach((v,k)=>near(v,s.point(0)[k]));
});
await scenario('dragging_a_point_moves_only_that_point',async s=>{
 s.fixture.anchors=[{host:{kind:'wall',id:'a'}}, {host:{kind:'wall',id:'b'}}, null];
 await s.choose();const original=structuredClone(s.fixture.path),anchors=structuredClone(s.fixture.anchors),p=s.point(1),q=[p[0]+45,p[1]+15];
 // A nearer selectable piece under a selected handle still cannot receive its press.
 s.view.pickAll=()=>[{kind:'wall',id:'under',building:'b',distance:0}];
 await s.send('pointerdown',p);assert.equal(s.view.controls.enabled,false);assert.equal(s.tools.selection().id,null);
 await s.send('pointermove',q);assert.equal(s.sent.length,0);assert.notDeepEqual(s.handles()[1].screen,p);
 await s.send('pointerup',q);assert.equal(s.sent.length,1);
 const out=s.sent[0];assert.equal(out.op,'update_light_fixture');assert.equal(out.entity_id,'light.a');assert.equal(out.id,id);
 assert.deepEqual(out.change.path[0],original[0]);assert.deepEqual(out.change.path[2],original[2]);
 assert.notDeepEqual(out.change.path[1].slice(0,2),original[1].slice(0,2));near(out.change.path[1][2],original[1][2]);
 assert.deepEqual(out.change.anchors,[anchors[0],null,null]);assert.deepEqual(s.fixture.path,original);
 assert.equal(s.selections.some(p=>p?.id==='under'),false);assert.equal(s.view.controls.enabled,true);
 assert.equal(document.getElementById('piece-card').dataset.fixtureCard,'light.a');
});
await scenario('snapped_run_has_no_point_handles',async s=>{
 await s.choose();assert.equal(s.handles().length,0);assert.equal(s.tools.handleAt(event(s.point(1))),false);
},{fixture:{...line(),snap:{host:{kind:'fence',id:'f'},edge:{from:[10,10],to:[30,10]},t0:0,t1:1}}});
await scenario('path_effect_point_drag_sends_its_op',async s=>{
 await s.choose();assert.equal(s.handles().length,3);const p=s.point(0),q=[p[0]+35,p[1]];
 await s.send('pointerdown',p);await s.send('pointermove',q);await s.send('pointerup',q);
 assert.equal(s.sent.length,1);const out=s.sent[0];assert.equal(out.op,'update_effect_fixture');assert.equal(out.id,effectId);
 assert.deepEqual(Object.keys(out.change),['path']);assert.deepEqual(out.change.path.slice(1),s.fixture.path.slice(1));
 near(out.change.path[0][2],s.fixture.path[0][2]);assert.notDeepEqual(out.change.path[0],s.fixture.path[0]);
 console.log('POINT_OP_CHECK '+JSON.stringify({plan:s.plan,operation:out}));
},{fixture:{...line(),id:effectId,type:'waterfall'},effect:true});
await scenario('unselected_fixture_press_navigates',async s=>{
 const p=s.point(1),before=JSON.stringify(s.plan);await s.send('pointerdown',p);assert.equal(s.view.controls.enabled,true);assert.equal(s.orbitPresses(),1);
 await s.send('pointermove',[p[0]+40,p[1]]);await s.send('pointermove',p);await s.send('pointerup',p);
 assert.ok(s.controlStates.every(Boolean));assert.equal(s.handles().length,0);assert.equal(s.sent.length,0);
 assert.equal(s.tools.selection().id,null);assert.equal(JSON.stringify(s.plan),before);
 await s.clickAt([p[0]+1,p[1]]);assert.equal(s.handles().length,3,'a later click selects the line');
});
await scenario('point_tremor_and_cancel_send_nothing',async s=>{
 await s.choose();const original=JSON.stringify(s.plan),p=s.point(1);
 await s.send('pointerdown',p);await s.send('pointermove',[p[0]+2,p[1]]);await s.send('pointerup',[p[0]+2,p[1]]);
 assert.equal(s.sent.length,0);
 await s.send('pointerdown',p);await s.send('pointermove',[p[0]+35,p[1]]);
 await fire(document,'keydown',{key:'Escape'});await s.send('pointerup',[p[0]+35,p[1]]);
 assert.equal(s.sent.length,0);assert.equal(s.view.controls.enabled,true);assert.equal(s.handles().length,3);
 assert.equal(JSON.stringify(s.plan),original);
});
await scenario('fixture_hits_keep_depth_occlusion_and_hidden_floor',async s=>{
 const towardCamera=p=>{const v=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048).lerp(s.view.camera.position,.1);return [v.x/.3048,-v.z/.3048,v.y/.3048];};
 const f={...s.fixture,id:'fixture:near',path:s.fixture.path.map(towardCamera)};
 s.plan.light_fixtures['light.a'].push(f);s.devices.refresh();
 const p=s.point(1),hits=s.devices.fixtureHits(...p);assert.deepEqual(hits.map(h=>h.id),['fixture:near',id]);
 assert.ok(hits.every((h,i)=>!i||hits[i-1].distance<=h.distance));
 s.view.pick=()=>({point:s.view.camera.position.clone().lerp(new THREE.Vector3(6,0,-3),.1).toArray()});
 assert.equal(s.devices.fixtureHits(...p).length,0);s.view.pick=()=>null;
 Object.assign(s.fixture,{ref:'floor',building:'b',level:'L'});s.view.groups.levels['b:L']={visible:false};s.devices.refresh();
 assert.equal(s.devices.fixtureHits(...p).some(h=>h.id===id),false);
});
await scenario('readonly_fixture_click_browses_and_drag_navigates',async s=>{
 const p=s.point(1);await s.send('pointerdown',p);assert.equal(s.orbitPresses(),1);await s.send('pointermove',[p[0]+40,p[1]]);await s.send('pointerup',[p[0]+40,p[1]]);
 assert.ok(s.controlStates.every(Boolean));assert.equal(s.sent.length,0);
 await s.clickAt(p);assert.equal(document.getElementById('piece-card').hidden,false);assert.equal(s.handles().length,0);
},{readonly:true});
await scenario('point_release_preserves_world_height_across_ground_and_offset',async s=>{
 Object.assign(s.fixture,{ref:'ground',offset_ft:1.25,facing:'down'});
 s.plan.site.terraces=[{id:'pad',polygon:[[19,9],[21,9],[21,11],[19,11]],height:2,blend:2}];s.devices.refresh();
 await s.choose();const before=resolveFixture(s.fixture,s.plan).path,p=s.point(1),q=[p[0]+100,p[1]+4];
 await s.send('pointerdown',p);await s.send('pointerup',q);assert.equal(s.sent.length,1,'release past the threshold also resolves its exact endpoint');
 const path=s.sent[0].change.path,after=resolveFixture({...s.fixture,path},s.plan).path;
 near(after[1][2],before[1][2]);assert.notEqual(path[1][2],s.fixture.path[1][2]);
 assert.deepEqual(path[0],s.fixture.path[0]);assert.deepEqual(path[2],s.fixture.path[2]);
 const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(q[0]/720-1,1-q[1]/450),s.view.camera);
 const end=ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0,1,0),-before[1][2]*.3048),new THREE.Vector3());
 near(after[1][0],end.x/.3048);near(after[1][1],-end.z/.3048);
});
await scenario('fixture_row_selection_survives_queued_toggles_after_refresh',async s=>{
 s.plan.light_fixtures['light.a'].push({...line(),id:'fixture:second',path:[[10,20,3],[20,20,6],[30,20,9]]});s.devices.refresh();await s.choose();
 const card=document.getElementById('piece-card');let first=card.querySelector(`[data-fixture-id="${id}"]`),second=card.querySelector('[data-fixture-id="fixture:second"]');
 second.open=true;await fire(second,'toggle');assert.equal(s.handles()[0].id,'fixture:second');
 first.open=false;await fire(first,'toggle');first.open=true;await fire(first,'toggle');assert.equal(s.handles()[0].id,id);
 s.plan.light_fixtures_meta={'light.a':{output_lm:600}};s.devices.refresh();
 for(const row of card.querySelectorAll('[data-fixture-id]')) await fire(row,'toggle');
 assert.equal(s.handles()[0].id,id,'restoring open rows must not select the last restored row');
 await fire(second,'toggle');assert.equal(s.handles()[0].id,id,'a detached old row must not own selection');
});
await scenario('point_cancel_permission_loss_and_nonleft_buttons_send_nothing',async s=>{
 await s.choose();const p=s.point(1),q=[p[0]+40,p[1]];
 for(const button of [1,2]){const count=s.orbitPresses();await s.send('pointerdown',p,{button});assert.equal(s.orbitPresses(),count+1);await s.send('pointermove',q,{button});await s.send('pointerup',q,{button});}
 await s.send('pointerdown',p);await s.send('pointermove',q);await s.send('pointercancel',q);assert.equal(s.sent.length,0);assert.equal(s.view.controls.enabled,true);
 await s.send('pointerdown',p);await s.send('pointermove',q);s.lock();s.devices.refresh();await s.send('pointerup',q);
 assert.equal(s.sent.length,0);assert.equal(s.handles().length,0);assert.equal(s.view.controls.enabled,true);
});
for(const type of ['sheer','fire','mist']) await scenario(type+'_path_point_has_handles_and_sends_effect_op',async s=>{
 await s.choose();const p=s.point(2);await s.send('pointerdown',p);await s.send('pointermove',[p[0]+35,p[1]]);await s.send('pointerup',[p[0]+35,p[1]]);
 assert.equal(s.sent.length,1);assert.equal(s.sent[0].op,'update_effect_fixture');
 console.log('POINT_OP_CHECK '+JSON.stringify({plan:s.plan,operation:s.sent[0]}));
},{fixture:{...line(),id:effectId,type},effect:true});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    lines = output.splitlines()
    print('\n'.join(line for line in lines if not line.startswith('POINT_OP_CHECK ')))
    if code == 0:
        sys.path.insert(0, str(ROOT))
        from services.twin_effect_fixtures import apply_op
        checks = [json.loads(line.removeprefix('POINT_OP_CHECK ')) for line in lines if line.startswith('POINT_OP_CHECK ')]
        for check in checks:
            apply_op(check['plan'], check['operation'])
            assert check['plan']['effect_fixtures'][0]['path'] == check['operation']['change']['path']
        print(f'  ok   JS point-drag payloads accepted by real effect server: {len(checks)}/{len(checks)}')
    sys.exit(code if code is not None else 1)
