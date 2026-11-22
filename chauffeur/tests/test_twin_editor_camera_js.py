"""Editor camera slice: production view/tools and vendored OrbitControls in node.

No browser or WebGL. Uses the real normalized household geometry, a renderer
stub, and capture/bubble event dispatch so gesture ownership is exercised.
"""
import json
from pathlib import Path
import re
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REAL_ORBIT = re.sub(r"  if \(spec === 'three/addons/controls/OrbitControls.js'\).*?shortCircuit: true};\n", '', PREFIX, flags=re.S)

DRIVER = REAL_ORBIT + r"""
const THREE = await import('three');
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
Object.assign(Renderer.prototype, {
  getDrawingBufferSize(v){return v.set(1440,900);}, getViewport(v){return v.set(0,0,1440,900);},setViewport(){},
  getScissor(v){return v.set(0,0,1440,900);},setScissor(){},getScissorTest(){return false;},setScissorTest(){},
  setAnimationLoop(fn){this.loop=fn;},
});
// Test-local faithful capture ordering; the shared small DOM intentionally only
// models bubbling. OrbitControls itself is NOT stubbed in this suite.
Element.prototype.addEventListener=function(type,fn,options={}) {
  if(options?.signal?.aborted)return;
  const entry={fn,capture:options===true||!!options.capture,once:!!options.once};
  (this._listeners[type] ||= []).push(entry);
  options.signal?.addEventListener('abort',()=>this.removeEventListener(type,fn),{once:true});
};
Element.prototype.dispatchEvent=function(event) {
  const e=event.__shim?event:makeEvent(event.type,{button:event.button,clientX:event.clientX,clientY:event.clientY,bubbles:event.bubbles});
  e.target ||= this;
  let stopped=false,immediate=false;
  e.stopPropagation=()=>{stopped=true;};e.stopImmediatePropagation=()=>{stopped=true;immediate=true;};
  const path=[];for(let n=this;n;n=n.parentElement)path.push(n);
  if(path.includes(document)&&!path.includes(window))path.push(window);
  const visit=(n,capture)=>{
    e.currentTarget=n;
    for(const entry of [...(n._listeners[e.type]||[])]) {
      if(entry.capture!==capture)continue;
      if(entry.once)n.removeEventListener(e.type,entry.fn);
      const result=entry.fn.call(n,e);if(result?.then)e._promises.push(result);
      if(immediate)break;
    }
  };
  for(let i=path.length-1;i>=0&&!stopped;--i)visit(path[i],true);
  if(!stopped)visit(this,false);
  if(e.bubbles)for(let i=1;i<path.length&&!stopped;++i)visit(path[i],false);
  return !e.defaultPrevented;
};
globalThis.MouseEvent=class {constructor(type,opts){Object.assign(this,{type,...opts});}};
const realNow=performance.now.bind(performance);
let clock=null;
Object.defineProperty(globalThis,'performance',{value:{now:()=>clock??realNow()},configurable:true});
window.fetch=globalThis.fetch=async()=>({ok:true,status:200,json:async()=>({materials:[],items:[],imports:[],entries:{},revision:0}),text:async()=>'{"entries":{}}'});
const storedSpeed=new Map();window.sessionStorage={getItem:k=>storedSpeed.get(k)??null,setItem:(k,v)=>storedSpeed.set(k,v)};
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const {groundAt}=await import(file('static/twin/twin_ground.js'));
const shell=new Element('main');shell.className='editor-shell';document.body.append(shell);
const host=new Element();shell.append(host);
const plan=structuredClone(input.flat),kit=input.kit,FT=.3048;
const view=await mountTwin(host,{plan,kit,tier:'low',bake:false,preserveCamera:true});
clock=1000;
const abort=new AbortController(),ops=[];
const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>kit,getSheets:()=>({}),
  op:async o=>ops.push(o),edit:async o=>ops.push(o),panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:abort.signal});
tools.setTool('select');
const canvas=view.renderer3.domElement,ctl=view.controls,fly=view.editorCamera;
const ev=(node,type,extra={})=>{const e=makeEvent(type,extra);node.dispatchEvent(e);return e;};
const ptr=(type,x=700,y=400,button=2,extra={})=>ev(canvas,type,{pointerType:'mouse',pointerId:10,button:type==='pointermove'?-1:button,buttons:type==='pointerup'?0:button===2?2:button===1?4:1,clientX:x,clientY:y,...extra});
const key=(type,k,target=canvas)=>ev(target,type,{key:k});
const down=()=>ptr('pointerdown'),release=()=>ptr('pointerup');
const frame=dt=>{clock+=dt;view.renderer3.loop();};
const closeMenu=()=>{const m=document.getElementById('editor-context-menu');m.hidden=true;document.activeElement=null;};
function pose(position=[0,20,30],target=[0,20,0]) {
  release();fly.stop();closeMenu();ctl.enabled=true;tools.setTool('select');
  view.setCamera('front');view.setCameraState({position,target});
}
const near=(a,b,eps=1e-8)=>assert.ok(Math.abs(a-b)<eps,`${a} != ${b}`);
const sameDelta=(p,t)=>{
  const dp=view.camera.position.clone().sub(p),dt=ctl.target.clone().sub(t);
  assert.ok(dp.distanceTo(dt)<1e-8);return dp;
};
const travel=(k,seconds,hz)=>{
  pose();down();const p=view.camera.position.clone(),t=ctl.target.clone();key('keydown',k);
  for(let i=0;i<seconds*hz;i++)frame(1000/hz);
  const d=sameDelta(p,t);release();return d;
};
await test('editor_mouse_map_and_screen_plane_pan',()=>{
  assert.deepEqual(ctl.mouseButtons,{LEFT:null,MIDDLE:THREE.MOUSE.PAN,RIGHT:null});assert.equal(ctl.screenSpacePanning,true);
  pose();const q=view.camera.quaternion.clone(),p=view.camera.position.clone();ptr('pointerdown',700,400,1);ptr('pointermove',750,430,1);ptr('pointerup',750,430,1);
  assert.ok(view.camera.position.distanceTo(p)>.01);assert.ok(view.camera.quaternion.angleTo(q)<1e-7);
});
await test('viewer_and_panel_keep_default_mouse_and_touch_map',async()=>{
  for(const search of ['?test=1','?panel=true&kiosk=true']) {
    location.search=search;const savedClock=clock;clock=null;const v=await mountTwin(new Element(),{plan,kit,tier:'low',bake:false});clock=savedClock;
    assert.equal(v.editorCamera,undefined);assert.deepEqual(v.controls.mouseButtons,{LEFT:THREE.MOUSE.ROTATE,MIDDLE:THREE.MOUSE.DOLLY,RIGHT:THREE.MOUSE.PAN});
    assert.deepEqual(v.controls.touches,{ONE:THREE.TOUCH.ROTATE,TWO:THREE.TOUCH.DOLLY_PAN});v.dispose();
  }location.search='?test=1';
  assert.deepEqual(ctl.touches,{ONE:THREE.TOUCH.ROTATE,TWO:THREE.TOUCH.DOLLY_PAN});
});
await test('right_click_under_four_pixels_opens_existing_menu',()=>{
  pose();down();ptr('pointermove',703,400);ptr('pointerup',703,400);ev(canvas,'contextmenu',{button:2,clientX:703,clientY:400});
  assert.equal(document.getElementById('editor-context-menu').hidden,false);closeMenu();
});
await test('right_drag_looks_right_in_place_and_suppresses_menu_even_after_returning',()=>{
  pose();const p=view.camera.position.clone(),distance=p.distanceTo(ctl.target);down();ptr('pointermove',730,400);
  const f=view.camera.getWorldDirection(new THREE.Vector3());near(Math.atan2(f.x,-f.z),30*.15*Math.PI/180);
  assert.ok(view.camera.position.distanceTo(p)<1e-8);near(ctl.target.distanceTo(p),distance);
  assert.ok(ctl.target.clone().sub(p).normalize().distanceTo(f)<1e-8);
  ptr('pointermove',700,400);release();ev(canvas,'contextmenu',{button:2,clientX:700,clientY:400});assert.equal(document.getElementById('editor-context-menu').hidden,true);
});
await test('look_up_and_down_clamp_at_89_degrees_and_survive_updates_zoom_and_fly',()=>{
  for(const sign of [-1,1]) {
    pose();const p=view.camera.position.clone(),distance=p.distanceTo(ctl.target),pitch=Math.asin(view.camera.getWorldDirection(new THREE.Vector3()).y);down();ptr('pointermove',700,400-sign*100);
    let f=view.camera.getWorldDirection(new THREE.Vector3());near(Math.asin(f.y),pitch+sign*15*Math.PI/180);
    ptr('pointermove',700,400-sign*2000);frame(16);f=view.camera.getWorldDirection(new THREE.Vector3());
    near(Math.asin(f.y),sign*89*Math.PI/180);assert.ok(view.camera.position.distanceTo(p)<1e-8);near(ctl.target.distanceTo(p),distance);
    assert.ok(ctl.target.clone().sub(p).normalize().distanceTo(f)<1e-8);
    near(new THREE.Vector3(1,0,0).applyQuaternion(view.camera.quaternion).y,0);
    key('keydown','w');const before=view.camera.position.clone(),target=ctl.target.clone();frame(100);
    assert.ok(sameDelta(before,target).normalize().distanceTo(f)<1e-8);release();
    ev(canvas,'wheel',{deltaY:-100,deltaMode:0});frame(16);assert.ok(view.camera.getWorldDirection(new THREE.Vector3()).distanceTo(f)<1e-8);
  }
});
await test('look_deltas_are_independent_of_event_and_frame_rate_and_w_follows_new_view',()=>{
  pose();down();ptr('pointermove',820,340);const expected=view.camera.getWorldDirection(new THREE.Vector3());release();
  pose();down();for(let i=1;i<=12;i++){ptr('pointermove',700+i*10,400-i*5);frame(1000/144);}
  assert.ok(view.camera.getWorldDirection(new THREE.Vector3()).distanceTo(expected)<1e-8);
  const p=view.camera.position.clone(),t=ctl.target.clone();key('keydown','w');frame(100);
  assert.ok(sameDelta(p,t).normalize().distanceTo(expected)<1e-8);release();
});
await test('alt_left_orbits_fixed_pivot_without_marquee_selection_or_edit',()=>{
  for(const extra of [{},{ctrlKey:true},{metaKey:true},{shiftKey:true}]) {
    pose();down();ptr('pointermove',700,0);release(); // Look above the old orbit limit first.
    const p=view.camera.position.clone(),target=ctl.target.clone(),members=tools.selectionStore.members();
    ptr('pointerdown',-2000,-2000,0,{altKey:true,...extra});ptr('pointermove',-1900,-1950,0,{altKey:true,...extra});
    assert.equal(ctl.enabled,true);assert.equal(document.getElementById('editor-drag-outline').getAttribute('points')||'','');
    ptr('pointerup',-1900,-1950,0,{altKey:true,...extra});
    assert.ok(view.camera.position.distanceTo(p)>.01);assert.ok(ctl.target.distanceTo(target)<1e-8);
    assert.ok(ctl.getPolarAngle()<=Math.PI*.49+1e-8);assert.deepEqual(tools.selectionStore.members(),members);
    // An Alt-click on a real piece must also bypass selection and handles.
    view.setPlanCamera('pool-house:L1');const item=view.selectionBounds().find(r=>r.kind==='wall'&&r.buildingId==='pool-house');assert.ok(item);
    const x=(item.bounds.left+item.bounds.right)/2,y=(item.bounds.top+item.bounds.bottom)/2;
    ptr('pointerdown',x,y,0,{altKey:true});ptr('pointerup',x,y,0,{altKey:true});assert.deepEqual(tools.selectionStore.members(),members);
  }
});
await test('alt_left_bypasses_armed_tools_including_measure_clicks',()=>{
  for(const tool of ['move','rotate','scale','measure','draw-wall']) {
    pose();tools.setTool(tool);const p=view.camera.position.clone(),target=ctl.target.clone();
    ptr('pointerdown',700,400,0,{altKey:true});ptr('pointermove',760,420,0,{altKey:true});ptr('pointerup',760,420,0,{altKey:true});
    assert.ok(view.camera.position.distanceTo(p)>.01);assert.ok(ctl.target.distanceTo(target)<1e-8);assert.equal(ctl.enabled,true);
    ptr('pointerdown',700,400,0,{altKey:true});ptr('pointerup',700,400,0,{altKey:true});
    if(tool==='measure')assert.ok(document.getElementById('editor-status').textContent.includes('Click the first point'));
    assert.equal(host.querySelector('.editor-measure').children.length,0);assert.deepEqual(tools.selectionStore.members(),[]);
  }
});
await test('look_respects_inputs_dialogs_disabled_controls_and_pointer_identity',()=>{
  for(const guard of ['input','dialog','disabled','other-pointer']) {
    pose();let node;
    if(guard==='input'){node=new Element('input');shell.append(node);node.focus();}
    if(guard==='dialog'){node=new Element();node.setAttribute('role','dialog');document.body.append(node);}
    if(guard==='disabled')ctl.enabled=false;
    const p=view.camera.position.clone(),target=ctl.target.clone(),q=view.camera.quaternion.clone();down();
    ptr('pointermove',780,340,2,guard==='other-pointer'?{pointerId:11}:{});frame(16);
    assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.ok(ctl.target.distanceTo(target)<1e-8);assert.ok(view.camera.quaternion.angleTo(q)<1e-7);
    release();node?.remove();document.activeElement=null;ctl.enabled=true;
  }
});
await test('modifier_keys_keep_right_look_and_middle_pan',()=>{
  for(const modifier of ['ctrlKey','metaKey','shiftKey']) {
    pose();let q=view.camera.quaternion.clone();const before=view.camera.position.clone();ptr('pointerdown',700,400,2,{[modifier]:true});ptr('pointermove',750,430,2,{[modifier]:true});ptr('pointerup',750,430,2);assert.ok(view.camera.quaternion.angleTo(q)>.01);assert.ok(view.camera.position.distanceTo(before)<1e-8);
    pose();q=view.camera.quaternion.clone();const p=view.camera.position.clone();ptr('pointerdown',700,400,1,{[modifier]:true});ptr('pointermove',750,430,1,{[modifier]:true});ptr('pointerup',750,430,1);assert.ok(view.camera.position.distanceTo(p)>.01);assert.ok(view.camera.quaternion.angleTo(q)<1e-7);
  }
});
await test('press_time_contextmenu_is_deferred_and_only_click_opens',()=>{
  pose();down();ev(canvas,'contextmenu',{button:2,clientX:700,clientY:400});assert.equal(document.getElementById('editor-context-menu').hidden,true);
  release();assert.equal(document.getElementById('editor-context-menu').hidden,false);closeMenu();
  down();ev(canvas,'contextmenu',{button:2,clientX:700,clientY:400});ptr('pointermove',710,400);ptr('pointerup',710,400);
  assert.equal(document.getElementById('editor-context-menu').hidden,true);
});
await test('empty_left_drag_is_marquee_without_camera_motion',()=>{
  pose();const p=view.camera.position.clone(),t=ctl.target.clone();
  ptr('pointerdown',-2000,-2000,0);ptr('pointermove',-1800,-1800,0);
  assert.ok(document.getElementById('editor-drag-outline').getAttribute('points'));assert.equal(ctl.enabled,false);
  ptr('pointerup',-1800,-1800,0);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.ok(ctl.target.distanceTo(t)<1e-8);assert.equal(ctl.enabled,true);
});
await test('piece_press_clicks_but_drag_starts_marquee_at_threshold_point',()=>{
  pose();const b=plan.buildings.find(b=>b.id==='pool-house');view.setView(b.id+':L1');view.setPlanCamera(b.id+':L1');
  const item=view.selectionBounds().find(r=>r.buildingId===b.id&&r.kind==='wall');assert.ok(item);
  const x=(item.bounds.left+item.bounds.right)/2,y=(item.bounds.top+item.bounds.bottom)/2;
  const p=view.camera.position.clone();
  ptr('pointerdown',x,y,0);ptr('pointerup',x,y,0);assert.ok(tools.selectionStore.members().length,'ordinary piece click selects');
  tools.select(null); // A passive body press, away from any selected shape handle.
  ptr('pointerdown',x,y,0);ptr('pointermove',x+5,y+5,0);
  assert.ok(document.getElementById('editor-drag-outline').getAttribute('points').startsWith(`${x+5},${y+5}`));
  ptr('pointermove',x+60,y+60,0);ptr('pointerup',x+60,y+60,0);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.equal(ctl.enabled,true);view.setView('ext');
});
await test('ordinary_wheel_dollies_and_right_wheel_changes_speed_readout',async()=>{
  pose();const d=view.camera.position.distanceTo(ctl.target);ev(canvas,'wheel',{deltaY:-100,deltaMode:0});assert.ok(view.camera.position.distanceTo(ctl.target)<d);
  down();const before=view.camera.position.clone(),speed=fly.speed();ev(canvas,'wheel',{deltaY:-100,deltaMode:0});near(fly.speed(),speed*1.25);
  assert.equal(storedSpeed.get('chauffeur_editor_fly_speed'),'15');
  assert.ok(view.camera.position.distanceTo(before)<1e-8);const out=host.querySelector('.editor-camera-speed');assert.equal(out.textContent,'Speed 15 ft/s');assert.equal(out.hidden,false);
  await new Promise(r=>setTimeout(r,1050));assert.equal(out.hidden,true);release();
});
await test('speed_clamps_one_to_two_hundred_and_is_session_remembered',async()=>{
  pose();down();for(let i=0;i<40;i++)ev(canvas,'wheel',{deltaY:-100});assert.equal(fly.speed(),200);
  for(let i=0;i<60;i++)ev(canvas,'wheel',{deltaY:100});assert.equal(fly.speed(),1);release();
  const other=new Element();shell.append(other);const savedClock=clock;clock=null;const v=await mountTwin(other,{plan,kit,tier:'low',bake:false});clock=savedClock;assert.equal(v.editorCamera.speed(),1);v.dispose();
  down();for(let i=0;i<11;i++)ev(canvas,'wheel',{deltaY:-100});release();
});
await test('fly_is_time_based_and_translates_target_with_camera',()=>{
  const a=travel('w',2,30),b=travel('w',2,144);assert.ok(a.distanceTo(b)<1e-8);
  near(a.length(),fly.speed()*FT*(2-.1*(1-Math.exp(-20))));
});
await test('wasd_directions_and_qe_world_up',()=>{
  assert.ok(travel('w',1,60).z<0);assert.ok(travel('s',1,60).z>0);
  assert.ok(travel('a',1,60).x<0);assert.ok(travel('d',1,60).x>0);
  const q=travel('q',1,60),e=travel('e',1,60);assert.ok(q.y<0&&e.y>0);near(q.x,0);near(e.z,0);
});
await test('diagonal_flight_keeps_the_selected_speed',()=>{
  const single=travel('w',1,60);pose();down();const p=view.camera.position.clone();key('keydown','w');key('keydown','d');
  for(let i=0;i<60;i++)frame(1000/60);near(view.camera.position.distanceTo(p),single.length());release();
});
await test('forward_follows_pitch_and_qe_remain_world_vertical',()=>{
  pose([0,20,30],[0,0,0]);down();const p=view.camera.position.clone(),t=ctl.target.clone();key('keydown','w');frame(100);const d=sameDelta(p,t);
  assert.ok(d.y<0&&d.z<0);near(d.y/d.z,20/30);
  release();pose([0,20,30],[0,0,0]);down();const p2=view.camera.position.clone();key('keydown','e');frame(100);near(view.camera.position.x,p2.x);near(view.camera.position.z,p2.z);assert.ok(view.camera.position.y>p2.y);
});
await test('keyup_eases_out_without_an_abrupt_velocity_step',()=>{
  pose();down();key('keydown','w');frame(200);const before=view.camera.position.z;key('keyup','w');frame(50);assert.ok(view.camera.position.z<before);release();
});
await test('keys_without_right_button_do_nothing',()=>{
  pose();const p=view.camera.position.clone();for(const k of 'wasdqe')assert.equal(key('keydown',k).defaultPrevented,false);frame(1000);assert.ok(view.camera.position.distanceTo(p)<1e-8);
});
await test('fly_keys_capture_before_other_editor_shortcuts',()=>{
  pose();let other=0;const fn=()=>other++;document.addEventListener('keydown',fn);down();
  for(const k of 'wasdqe')assert.equal(key('keydown',k).defaultPrevented,true);assert.equal(other,0);release();document.removeEventListener('keydown',fn);
});
await test('text_inputs_selects_and_contenteditable_ignore_keys',()=>{
  for(const tag of ['input','textarea','select','div']) {
    pose();const input=new Element(tag);if(tag==='div')input.setAttribute('contenteditable','');shell.append(input);input.focus();down();
    const p=view.camera.position.clone();assert.equal(key('keydown','w',input).defaultPrevented,false);frame(200);assert.ok(view.camera.position.distanceTo(p)<1e-8);input.remove();document.activeElement=null;release();
  }
});
await test('global_prompts_alerts_and_editor_dialog_block_fly',()=>{
  for(const id of ['cc-confirm-modal','cc-input-modal','cc-alert-modal','cc-choice-modal','editor-dialog']) {
    pose();const modal=new Element();modal.id=id;if(id==='editor-dialog')modal.setAttribute('role','dialog');document.body.append(modal);
    down();const p=view.camera.position.clone();assert.equal(key('keydown','w').defaultPrevented,false);frame(200);assert.ok(view.camera.position.distanceTo(p)<1e-8);modal.remove();release();
  }
});
await test('opening_a_dialog_during_fly_clears_motion',()=>{
  pose();down();key('keydown','w');frame(100);const modal=new Element();modal.id='cc-alert-modal';document.body.append(modal);const p=view.camera.position.clone();frame(100);modal.remove();frame(100);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.equal(fly.active(),false);release();
});
await test('blur_visibility_and_pointercancel_clear_held_state',()=>{
  for(const [node,type] of [[window,'blur'],[document,'visibilitychange'],[canvas,'pointercancel']]) {
    pose();down();key('keydown','w');frame(100);ev(node,type,{pointerId:10});const p=view.camera.position.clone();frame(1000);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.equal(fly.active(),false);
    assert.equal(key('keydown','w').defaultPrevented,false);release();
  }
});
await test('ground_clamp_uses_real_pad_height_and_translates_target',()=>{
  pose();const saved=view.plan.site;view.plan.site={...saved,terraces:[{polygon:[[-10,-10],[10,-10],[10,10],[-10,10]],height:8,blend:0}]};
  view.setCameraState({position:[0,8*FT+.21,0],target:[0,8*FT+.21,-10]});down();const p=view.camera.position.clone(),t=ctl.target.clone();key('keydown','q');frame(1000);sameDelta(p,t);near(view.camera.position.y,8*FT+.2);view.plan.site=saved;release();
});
await test('top_right_drag_cannot_rotate_and_middle_drag_pans',()=>{
  pose();down();ptr('pointermove',700,0);release();view.setPlanCamera('pool-house:L1');assert.ok(view.camera.isOrthographicCamera);
  assert.ok(view.camera.getWorldDirection(new THREE.Vector3()).distanceTo(new THREE.Vector3(0,-1,0))<.00001);
  const q=view.camera.quaternion.clone(),p=view.camera.position.clone();down();ptr('pointermove',770,450);ptr('pointerup',770,450);assert.ok(view.camera.quaternion.angleTo(q)<1e-7);assert.ok(view.camera.position.distanceTo(p)<1e-8);
  ptr('pointerdown',700,400,0,{altKey:true});ptr('pointermove',770,450,0,{altKey:true});ptr('pointerup',770,450,0,{altKey:true});assert.ok(view.camera.quaternion.angleTo(q)<1e-7);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.equal(document.getElementById('editor-drag-outline').getAttribute('points')||'','');
  ptr('pointerdown',700,400,1);ptr('pointermove',740,420,1);ptr('pointerup',740,420,1);assert.ok(view.camera.position.distanceTo(p)>.01);assert.ok(view.camera.quaternion.angleTo(q)<1e-7);
});
await test('top_wasd_pan_screen_axes_and_qe_zoom',()=>{
  for(const k of 'wasdqe') {
    pose();view.setPlanCamera('pool-house:L1');const p=view.camera.position.clone(),t=ctl.target.clone(),zoom=view.camera.zoom;
    const up=new THREE.Vector3(0,1,0).applyQuaternion(view.camera.quaternion),right=new THREE.Vector3(1,0,0).applyQuaternion(view.camera.quaternion);
    down();key('keydown',k);frame(200);const d=sameDelta(p,t);
    if(k==='w')assert.ok(d.dot(up)>0);if(k==='s')assert.ok(d.dot(up)<0);if(k==='a')assert.ok(d.dot(right)<0);if(k==='d')assert.ok(d.dot(right)>0);
    if(k==='q')assert.ok(view.camera.zoom<zoom);if(k==='e')assert.ok(view.camera.zoom>zoom);release();
  }
});
await test('top_wheel_zooms_but_right_wheel_only_changes_speed',()=>{
  pose();view.setPlanCamera('pool-house:L1');const zoom=view.camera.zoom;ev(canvas,'wheel',{deltaY:-100,deltaMode:0});assert.ok(view.camera.zoom>zoom);
  down();const z=view.camera.zoom,speed=fly.speed();ev(canvas,'wheel',{deltaY:100,deltaMode:0});assert.ok(fly.speed()<speed);near(view.camera.zoom,z);release();
});
await test('fly_preserves_existing_maximum_orbit_distance',()=>{
  pose();const old=ctl.maxDistance;ctl.maxDistance=20;ctl.update();down();key('keydown','w');key('keydown','e');frame(500);near(view.camera.position.distanceTo(ctl.target),20);release();ctl.maxDistance=old;
});
await test('escape_stops_fly_before_selection_and_next_escape_keeps_order',()=>{
  pose();const b=plan.buildings.find(b=>b.id==='pool-house'),w=b.walls[0];tools.select({kind:'wall',id:w.id,building:b.id});
  down();key('keydown','w');frame(100);const p=view.camera.position.clone();const esc=key('keydown','Escape');assert.equal(esc.defaultPrevented,true);assert.equal(fly.active(),false);assert.ok(tools.selectionStore.members().length);
  ev(canvas,'keydown',{key:'w',repeat:true});frame(100);assert.ok(view.camera.position.distanceTo(p)<1e-8);release();
  key('keydown','Escape');assert.equal(tools.selectionStore.members().length,0);
});
await test('tool_disabled_controls_block_flying_and_clear_velocity',()=>{
  pose();down();key('keydown','w');frame(100);ctl.enabled=false;const p=view.camera.position.clone();frame(500);assert.ok(view.camera.position.distanceTo(p)<1e-8);assert.equal(fly.active(),false);key('keydown','d');frame(100);assert.ok(view.camera.position.distanceTo(p)<1e-8);ctl.enabled=true;frame(100);assert.ok(view.camera.position.distanceTo(p)<1e-8);release();
});
assert.equal(ops.length,0,'camera and selection gestures never edit the house');
abort.abort();view.dispose();finish();
"""

if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'flat': flatten(assemble(fixture)[0]), 'kit': kit}, timeout=240)
    print(out)
    sys.exit(code or 0)
