"""Tool arbitration through real scene tools, library, lot, handles and CPU rays.

No browser is started; eight camera-binding cases use vendored OrbitControls,
and the other cases keep the existing CPU harness double.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as DRAG_DRIVER

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE = await import(three);
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {createLibrary} = await import(file('static/twin/editor/library.js'));
const {createTerrainTools} = await import(file('static/twin/editor/terrain_tools.js'));
const {createLotTools} = await import(file('static/twin/editor/lot_tools.js'));
const {OrbitControls: RealOrbitControls} = await import(file('static/vendor/three-r187/addons/controls/OrbitControls.js'));
const nodes = new Map(), doc = new Element();
const shell = new Element(), descendants = n => n.children.flatMap(c=>[c,...descendants(c)]);
Element.prototype.getAttribute = function(k) { return this[k]; };
Element.prototype.querySelectorAll = function(selector) { return descendants(this).filter(n=>selector.split(',').includes(n.tag)); };
Element.prototype.querySelector = () => null;
Element.prototype.setPointerCapture = function(id) { this.capture = id; };
Element.prototype.hasPointerCapture = function(id) { return this.capture === id; };
Element.prototype.releasePointerCapture = function() { this.capture = null; };
doc.createElement = tag => Object.assign(new Element(),{tag});
doc.createElementNS = (_, tag) => doc.createElement(tag);
doc.getElementById = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
doc.querySelector = selector => selector==='.editor-shell'?shell:null; doc.querySelectorAll = () => []; globalThis.document = doc;
// Node's EventTarget uses registration order. Model document capture before
// bubble so the ground card's capture listener competes with the real arbiter.
doc.closest = () => null;
const addDocumentListener=doc.addEventListener.bind(doc), dispatchDocumentEvent=doc.dispatchEvent.bind(doc);
let keyListeners=[];
doc.addEventListener=(type,listener,options={})=>{
  if(type!=='keydown')return addDocumentListener(type,listener,options);
  keyListeners=keyListeners.filter(row=>!row.signal?.aborted);
  keyListeners.push({listener,capture:options===true||!!options.capture,signal:options.signal});
};
doc.dispatchEvent=event=>{
  if(event.type!=='keydown')return dispatchDocumentEvent(event);
  Object.defineProperty(event,'target',{value:doc});
  let stopped=false;event.stopImmediatePropagation=()=>{stopped=true;};
  for(const capture of [true,false])for(const row of keyListeners) {
    if(stopped)return !event.defaultPrevented;
    if(row.capture===capture&&!row.signal?.aborted)row.listener(event);
  }
  return !event.defaultPrevented;
};
const escape=()=>{const event=new Event('keydown',{cancelable:true});Object.assign(event,{key:'Escape'});doc.dispatchEvent(event);};
window.showGlobalAlert = message => { throw Error(message); };
globalThis.fetch = async () => new Response(JSON.stringify({limit_mb:50,unpacked_limit_mb:200,entries:{},revision:1,materials:[],items:[],imports:[]}));
globalThis.requestAnimationFrame = () => 1;
globalThis.cancelAnimationFrame = () => {};
flat.site = {planting:[{id:'tree:gesture',kind:'tree',at:[200,200],height:10}],
  beds:[{id:'bed:gesture',polygon:[[190,190],[210,190],[210,210],[190,210]]}]};
const B='pool-house', W='wall:9adea4c38eb2430697cf47d4ddee9d2a';
const building=flat.buildings.find(b=>b.id===B), wall=building.walls.find(w=>w.id===W);
let passed=0, failed=0;
const tick=()=>new Promise(r=>setTimeout(r,0));
async function test(name, body) {
  const view=await mountTwin(new Element(),{plan:flat,kit,tier:'low',preserveCamera:true});
  const abort=new AbortController(), ops=[], controlStates=[];
  let library, terrain, enabled=true, writable=true, saveGate=null, ordinaryPresses=0;
  Object.defineProperty(view.controls,'enabled',{get:()=>enabled,set:value=>{enabled=value;controlStates.push(value);}});
  const op=async(operation,options)=>{ops.push({operation,options});if(saveGate)await saveGate;};
  const originalResizeObserver=globalThis.ResizeObserver;let resizeCanvas=null;
  globalThis.ResizeObserver=class extends originalResizeObserver {
    constructor(callback){super(callback);this.callback=callback;}
    observe(node){super.observe(node);if(node===view.renderer3.domElement.parentElement)resizeCanvas=this.callback;}
  };
  const tools=createSceneTools({view,getPlan:()=>flat,getModel:()=>flat,getKit:()=>kit,getSheets:()=>({}),op,edit:op,
    panel:{clearSelection(){},focusSelection(){}},canEdit:()=>writable,signal:abort.signal,
    siteHits:(x,y)=>library?.siteHits(x,y) || [],pickSite:(x,y)=>library?.pickSite(x,y),padHits:(x,y)=>terrain?.padHits?.(x,y)||[]});
  globalThis.ResizeObserver=originalResizeObserver;
  library=createLibrary({view,kit,getPlan:()=>flat,tools,op,canEdit:()=>true,signal:abort.signal});
  terrain=createTerrainTools({view,tools,getPlan:()=>flat,op,canEdit:()=>writable,signal:abort.signal,pickObject:library.pickSite});
  doc.getElementById('place-view').hidden=true;
  const lot=createLotTools({view,getPlan:()=>flat,getSheets:()=>({}),getSelection:tools.selection,select:tools.select,
    pauses:{lotPlacement:()=>null},op,reload:async()=>{},canEdit:()=>writable,signal:abort.signal});
  tools.delegate({preview:library.preview,key:library.key,typedValue:library.typedValue,commit:library.commit,handleSources:[terrain,lot],pointerArmedDown:event=>terrain.pointerArmedDown?.(event)||lot.pointerArmedDown(event),
    selectPick:hit=>hit?.kind==='terraces'&&(terrain.choose('terraces',hit.id),true),
    pointerDown:event=>{ordinaryPresses++;return terrain.pointerDown(event)||lot.pointerDown(event)||library.pointerDown(event);},
    pointerMove:event=>terrain.pointerMove(event)||lot.pointerMove(event)||library.pointerMove(event),
    pointerUp:(event,cancel)=>terrain.pointerUp(event,cancel)||lot.pointerUp(event,cancel)||library.pointerUp(event,cancel),
    selectionChanged:state=>{terrain.selectionChanged(state);library.refresh();}});
  const canvas=view.renderer3.domElement;
  const world=(p,b=null)=>{
    const angle=(b?.rotation||0)*Math.PI/180, pos=b?.position||[0,0];
    return new THREE.Vector3((Math.cos(angle)*p[0]-Math.sin(angle)*p[1]+pos[0])*.3048,
      ((p[2]||0)+(b?.base||0))*.3048,-(Math.sin(angle)*p[0]+Math.cos(angle)*p[1]+pos[1])*.3048);
  };
  const look=(point,b=null,height=150)=>view.setCameraState({position:world([point[0],point[1]-.01,height],b).toArray(),target:world(point,b).toArray()});
  const pixel=(point,b=null)=>{const p=world(point,b).project(view.camera);return [(p.x+1)*720,(1-p.y)*450];};
  function fire(type,p,button=0,extra={}) {
    const event=new Event(type);Object.assign(event,{pointerId:1,button,buttons:type==='pointerdown'?1:0,clientX:p[0],clientY:p[1],...extra});
    (type==='pointerup'?doc:canvas).dispatchEvent(event);
  }
  const click=p=>{fire('pointerdown',p);fire('pointerup',p);};
  const ready=async()=>{while(!view.ready)await tick();};
  tools.setTool('select');
  try {await body({view,tools,library,terrain,lot,ops,controlStates,look,pixel,fire,click,ready,
    resizeCanvas:()=>{assert.ok(resizeCanvas);resizeCanvas();},
    ordinaryPresses:()=>ordinaryPresses,setSaveGate:value=>saveGate=value,setWritable:value=>writable=value});passed++;console.log('  ok '+name);}
  catch(error){failed++;console.error('  FAIL '+name+'\n'+error.stack);}
  finally {abort.abort();delete flat.site.terraces;await tick();view.dispose();}
}
// Opt in only the eight cases whose former left-navigation assertions changed.
// Keep the other 38 cases and their controls double untouched. The real controls
// consume the production editor's mouse map and enabled/target state. This small
// EventTarget DOM has no bubbling, so explicitly forward mouse moves to document.
async function cameraBindings({view,tools,fire,ops}, body) {
  const canvas=view.renderer3.domElement, controls=view.controls, owner=canvas.ownerDocument;
  canvas.ownerDocument=doc;
  const real=new RealOrbitControls(view.camera,canvas);
  real.target=controls.target;real.mouseButtons=controls.mouseButtons;
  real.maxPolarAngle=controls.maxPolarAngle;real.enableDamping=false;
  Object.defineProperty(real,'enabled',{get:()=>controls.enabled});real.update();
  function mouse(type,p,button=0) {
    const extra={pointerType:'mouse',button:type==='pointermove'?-1:button,
      buttons:type==='pointerup'?0:button===2?2:button===1?4:1};
    fire(type,p,button,extra);
    if(type==='pointermove') {
      const event=new Event(type);Object.assign(event,{pointerId:1,clientX:p[0],clientY:p[1],...extra});doc.dispatchEvent(event);
    }
  }
  async function navigate(p,button=2) {
    const position=view.camera.position.clone(),target=controls.target.clone(),rotation=view.camera.quaternion.clone();
    const members=tools.selectionStore.members(),count=ops.length;
    mouse('pointerdown',p,button);assert.equal(controls.enabled,true);
    mouse('pointermove',[p[0]+40,p[1]],button);mouse('pointerup',[p[0]+40,p[1]],button);await tick();
    assert.ok(view.camera.position.distanceTo(position)>1e-5,'navigation actually moves the camera');
    if(button===2) {
      assert.ok(view.camera.quaternion.angleTo(rotation)>1e-5,'right-drag actually orbits');
      assert.ok(controls.target.distanceTo(target)<1e-8,'right-drag retains its pivot');
    } else {
      assert.ok(view.camera.quaternion.angleTo(rotation)<1e-7,'middle-drag pans without rotating');
      assert.ok(view.camera.position.clone().sub(position).distanceTo(controls.target.clone().sub(target))<1e-8,'middle-drag carries the pivot');
    }
    assert.deepEqual(tools.selectionStore.members(),members,'navigation retains selection');assert.equal(ops.length,count);
    // Restore the camera so the next gesture addresses the same body pixel.
    view.setCameraState({position:position.toArray(),target:target.toArray()});real.update();
  }
  async function marquee(p) {
    const position=view.camera.position.clone(),target=controls.target.clone(),rotation=view.camera.quaternion.clone();
    const before=JSON.stringify(flat),count=ops.length;
    mouse('pointerdown',p);mouse('pointermove',[p[0]+40,p[1]]);
    assert.equal(controls.enabled,false,'left drag belongs to the marquee');
    assert.ok(doc.getElementById('editor-drag-outline').getAttribute('points'),'left drag draws the marquee');
    mouse('pointerup',[p[0]+40,p[1]]);await tick();
    assert.ok(view.camera.position.distanceTo(position)<1e-8,'left never translates the camera');
    assert.ok(controls.target.distanceTo(target)<1e-8,'left never pans the pivot');
    assert.ok(view.camera.quaternion.angleTo(rotation)<1e-7,'left never rotates the camera');
    assert.deepEqual(tools.selectionStore.members(),[],'a zero-height marquee replaces selection with its empty result');
    assert.equal(doc.getElementById('editor-drag-outline').getAttribute('points'),'');
    assert.equal(controls.enabled,true);assert.equal(ops.length,count);assert.equal(JSON.stringify(flat),before);
  }
  try {await body({orbit:p=>navigate(p),pan:p=>navigate(p,1),marquee});}
  finally {real.dispose();canvas.ownerDocument=owner;}
}
await test('pad_corner_wins_over_tree',async({view,tools,library,terrain,ops,look,fire,ordinaryPresses})=>{
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  look([200,200,0]);terrain.choose('terraces','pad:gesture');
  const h=terrain.handles().find(h=>!h.insert&&h.index===0),p=[h.screen[0]+12,h.screen[1]];
  assert.equal(library.siteHits(...p)[0]?.id,'tree:gesture','real tree box covers the pad corner press');
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);
  fire('pointermove',[p[0]+30,p[1]]);fire('pointerup',[p[0]+30,p[1]]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'update_pad');
  assert.notDeepEqual(ops[0].operation.polygon[0],[200,200]);
  assert.equal(tools.selection().id,null,'tree never selected');assert.equal(terrain.handles().length,8,'pad stays chosen');
  assert.equal(ordinaryPresses(),0,'handle wins before any ordinary delegate');assert.equal(view.controls.enabled,true);
});
await test('handle_radius_is_16',async({view,tools,ops,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  look([...wall.from,0],building);
  const h=tools.handles().find(h=>h.kind==='joint'&&h.id===wall.joints[0]),p=pixel(h.at,building);
  assert.equal(tools.handleAt({clientX:p[0]-17,clientY:p[1]}),false);
  fire('pointerdown',[p[0]-15,p[1]]);assert.equal(view.controls.enabled,false);
  fire('pointermove',[p[0]-45,p[1]]);fire('pointerup',[p[0]-45,p[1]]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_joint');assert.equal(view.controls.enabled,true);
});
await test('busy_pad_holds_its_handle',async({view,tools,terrain,ops,look,fire,setSaveGate,ordinaryPresses})=>{
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  look([200,200,0]);terrain.choose('terraces','pad:gesture');
  const p=terrain.handles()[0].screen;let release;
  setSaveGate(new Promise(resolve=>release=resolve));
  fire('pointerdown',p);fire('pointermove',[p[0]+30,p[1]]);fire('pointerup',[p[0]+30,p[1]]);
  assert.equal(ops.length,1);
  fire('pointerdown',p);assert.equal(view.controls.enabled,false,'pending save still captures the corner');
  fire('pointermove',[p[0]+30,p[1]]);assert.equal(ops.length,1,'second save waits');
  setSaveGate(null);release();await tick();
  fire('pointerup',[p[0]+30,p[1]]);await tick();
  assert.equal(ops.length,2,'held drag resumes after save');assert.equal(ops[1].operation.op,'update_pad');
  assert.equal(tools.selection().id,null);assert.equal(ordinaryPresses(),0);assert.equal(terrain.handles().length,8);
  assert.equal(view.controls.enabled,true);
});
await test('busy_pad_keeps_a_release_until_save_answers',async({view,terrain,ops,look,fire,setSaveGate})=>{
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  look([200,200,0]);terrain.choose('terraces','pad:gesture');const p=terrain.handles()[0].screen;let release;
  setSaveGate(new Promise(resolve=>release=resolve));
  fire('pointerdown',p);fire('pointermove',[p[0]+30,p[1]]);fire('pointerup',[p[0]+30,p[1]]);
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);
  assert.equal(ops.length,1);assert.equal(view.controls.enabled,true);
  setSaveGate(null);release();await tick();assert.equal(ops.length,2);assert.equal(ops[1].operation.op,'update_pad');
  assert.equal(view.controls.enabled,true);
});
await test('busy_pad_refuses_a_changed_corner_and_cancels_safely',async({view,tools,terrain,ops,look,fire,setSaveGate})=>{
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  look([200,200,0]);terrain.choose('terraces','pad:gesture');const p=terrain.handles()[0].screen,alerts=[];
  const previousAlert=window.showGlobalAlert;window.showGlobalAlert=message=>alerts.push(message);
  try {
    let release;setSaveGate(new Promise(resolve=>release=resolve));
    fire('pointerdown',p);fire('pointermove',[p[0]+30,p[1]]);fire('pointerup',[p[0]+30,p[1]]);
    fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);
    flat.site.terraces[0].polygon[0]=[201,200];setSaveGate(null);release();await tick();
    fire('pointerup',[p[0]+40,p[1]]);await tick();
    assert.equal(ops.length,1);assert.equal(alerts.length,1);assert.match(alerts[0],/pad changed/);
    assert.equal(tools.selection().id,null);assert.equal(view.controls.enabled,true);
    const q=terrain.handles()[0].screen;setSaveGate(new Promise(resolve=>release=resolve));
    fire('pointerdown',q);fire('pointermove',[q[0]+30,q[1]]);fire('pointerup',[q[0]+30,q[1]]);
    fire('pointerdown',q);fire('pointermove',[q[0]+40,q[1]]);fire('pointercancel',[q[0]+40,q[1]]);
    setSaveGate(null);release();await tick();assert.equal(ops.length,2);assert.equal(alerts.length,1);
    assert.equal(view.controls.enabled,true);
  } finally {window.showGlobalAlert=previousAlert;}
});
await test('armed_modes_then_first_handle_source_own_the_press',async({view,tools,fire})=>{
  let armed=true,beginWorks=true,hits=0,begins=0,ordinary=0,moves=0,ups=0;
  const handle={kind:'future-fixture-point'},source={hit(){hits++;return handle;},
    begin(event,chosen){assert.equal(chosen,handle);begins++;return beginWorks;},pointerMove(){moves++;},pointerUp(){ups++;}};
  tools.delegate({pointerArmedDown:()=>armed,handleSources:[source,{hit(){throw Error('later source must not be asked');}}],
    pointerDown(){ordinary++;return true;}});
  fire('pointerdown',[700,400]);fire('pointerup',[700,400]);assert.equal(hits,0);
  armed=false;fire('pointerdown',[700,400]);assert.equal(view.controls.enabled,false);assert.equal(view.renderer3.domElement.capture,1);
  fire('pointermove',[730,400]);fire('pointerup',[730,400]);
  assert.equal(begins,1);assert.equal(moves,1);assert.equal(ups,1);assert.equal(ordinary,0);assert.equal(view.controls.enabled,true);
  beginWorks=false;fire('pointerdown',[700,400]);assert.equal(view.controls.enabled,false);
  fire('pointermove',[730,400]);fire('pointerup',[730,400]);
  assert.equal(begins,2);assert.equal(moves,1);assert.equal(ups,1);assert.equal(ordinary,0);assert.equal(view.controls.enabled,true);
});
await test('unselected_press_navigates',async({view,tools,ops,controlStates,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]), before=JSON.stringify(flat);
  await cameraBindings({view,tools,fire,ops},async({orbit,pan,marquee})=>{
    await orbit(p);assert.equal(tools.selection().id,null);assert.equal(view.controls.enabled,true);
    await pan(p);assert.equal(view.controls.enabled,true);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,null);
    assert.ok(controlStates.every(Boolean));assert.equal(JSON.stringify(flat),before);
    await marquee(p);
  });
});
await test('jitter_under_threshold_is_a_click',async({tools,ops,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);
  fire('pointerdown',p);fire('pointermove',[p[0]+2,p[1]]);fire('pointerup',[p[0]+2,p[1]]);await tick();
  assert.equal(tools.selection().id,'tree:gesture');assert.equal(ops.length,0);
});
await test('selected_wall_body_does_not_move_with_select_tool',async({view,tools,ops,controlStates,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building,40);
  const p=pixel([...point,0],building);
  assert.equal(view.pick(...p)?.id,W,'press is on the actual wall');
  assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false,'body press is outside the drawn end and middle handles');
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);
    assert.equal(ops.length,0);assert.ok(controlStates.every(Boolean));assert.equal(view.controls.enabled,true);
    assert.equal(tools.selection().id,W);
    await marquee(p);
  });
});
await test('selected_wall_handle_still_moves',async({view,tools,ops,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  const mid=wall.from.map((v,i)=>(v+wall.to[i])/2);look([...mid,0],building);
  const p=pixel([...mid,0],building);assert.ok(tools.handleAt({clientX:p[0],clientY:p[1]}));
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);
  fire('pointermove',[p[0],p[1]+40]);fire('pointerup',[p[0],p[1]+40]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_wall');assert.equal(ops[0].options.drag,true);
  assert.equal(view.controls.enabled,true);
});
await test('click_cycles_through_stacked_things',async({tools,look,pixel,click})=>{
  look([200,200,0]);const p=pixel([200,200,0]);
  click(p);assert.equal(tools.selection().id,'tree:gesture');click(p);assert.equal(tools.selection().id,'bed:gesture');
});
await test('hover_shows_what_click_selects',async({tools,look,pixel,click,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);click(p);fire('pointermove',p);
  assert.equal(tools.selection().hover?.id,'bed:gesture');
  click(p);assert.equal(tools.selection().id,'bed:gesture');
});
await test('threshold_crossing_stays_navigation_after_returning_to_press',async({tools,ops,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);
  for(const distance of [3,40]) {
    fire('pointerdown',p);fire('pointermove',[p[0]+distance,p[1]]);fire('pointermove',p);fire('pointerup',p);
    assert.equal(tools.selection().id,null);assert.equal(ops.length,0);
  }
});
await test('right_and_middle_drag_leave_controls_and_hover_alone',async({tools,view,ops,controlStates,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);fire('pointermove',p);
  const hover=tools.selection().hover;
  for(const button of [1,2]) {
    fire('pointerdown',p,button);fire('pointermove',[p[0]+100,p[1]],button);
    assert.deepEqual(tools.selection().hover,hover);fire('pointerup',[p[0]+100,p[1]],button);
  }
  assert.equal(tools.selection().id,null);assert.equal(ops.length,0);
  assert.ok(controlStates.every(Boolean));assert.equal(view.controls.enabled,true);
});
await test('pinch_cancels_passive_click',async({tools,ops,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);fire('pointerdown',p);
  fire('pointerdown',p,0,{pointerId:2});fire('pointerup',p,0,{pointerId:2});fire('pointerup',p);
  assert.equal(tools.selection().id,null);assert.equal(ops.length,0);
});
await test('read_only_browse_delegate_keeps_its_press_and_release',async({tools,ops,fire,setWritable})=>{
  let downs=0,ups=0;setWritable(false);
  tools.delegate({pointerBrowse:()=>{downs++;return true;},pointerUp:()=>{ups++;return true;}});
  fire('pointerdown',[500,500]);fire('pointerup',[500,500]);
  assert.equal(downs,1);assert.equal(ups,1);assert.equal(tools.selection().id,null);assert.equal(ops.length,0);
});
await test('shift_click_add_room_still_focuses_the_room',async({view,tools,ops,pixel,look,fire,ready})=>{
  const room=building.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7');
  view.setView(B+':L1');tools.chooseFloor(B+':L1');await ready();
  const centre=[0,1].map(i=>room.polygon.reduce((sum,p)=>sum+p[i],0)/room.polygon.length);
  look([...centre,0],building);const p=pixel([...centre,0],building);
  fire('pointerdown',p,0,{shiftKey:true});fire('pointerup',p,0,{shiftKey:true});
  assert.equal(tools.selection().room,room.id);assert.deepEqual(tools.selectedRooms(),[room.id]);assert.equal(ops.length,0);
});
await test('yard_click_refreshes_its_selection_outline',async({view,look,pixel,click})=>{
  look([200,200,0]);click(pixel([200,200,0]));
  const outline=view.scene.children.find(o=>o instanceof THREE.Box3Helper);
  assert.ok(outline?.visible,'tree outline appears on release without waiting for a camera move or poll');
});
await test('move_tool_unselected_press_navigates',async({view,tools,ops,controlStates,look,pixel,fire})=>{
  look([200,200,0]);tools.setTool('move');const p=pixel([200,200,0]),before=JSON.stringify(flat);
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);assert.equal(view.controls.enabled,true);assert.equal(tools.selection().id,null);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,null);assert.ok(controlStates.every(Boolean));
    assert.equal(JSON.stringify(flat),before);
    await marquee(p);
  });
});
await test('move_tool_click_then_drag_moves',async({view,tools,ops,look,pixel,fire,click})=>{
  look([200,200,0]);tools.setTool('move');const p=pixel([200,200,0]);
  click(p);assert.equal(tools.selection().id,'tree:gesture');assert.equal(ops.length,0);
  assert.equal(view.controls.enabled,true);
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);
  fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_site_item');assert.equal(ops[0].options.drag,true);
  assert.equal(ops[0].operation.list,'planting');assert.equal(ops[0].operation.index,0);
  assert.notDeepEqual(ops[0].operation.at,[200,200]);assert.ok(ops[0].options.local);
  assert.deepEqual(ops[0].options.selection,{kind:'planting',id:'tree:gesture'});
  assert.equal(tools.selection().id,'tree:gesture');
  assert.equal(view.controls.enabled,true);
});
await test('move_tool_selected_building_body_moves',async({view,tools,lot,ops,look,pixel,fire})=>{
  view.setView('ext');tools.select({kind:'building',id:B,building:B});tools.setTool('move');
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building,40);
  const p=pixel([...point,0],building);assert.equal(view.pick(...p)?.building,B);
  assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false,'press is on body away from drawn handles');
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);assert.ok(lot.dragging());
  fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.length,1);
  assert.equal(ops[0].operation[0].op,'move_building');assert.equal(ops[0].operation[0].building,B);
  assert.notDeepEqual(ops[0].operation[0].to,building.position);
  assert.equal(tools.selection().id,B);assert.equal(view.controls.enabled,true);
});
await test('esc_cancels_body_drag',async({view,tools,lot,ops,look,pixel,fire})=>{
  view.setView('ext');tools.select({kind:'building',id:B,building:B});tools.setTool('move');
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building,40);
  const p=pixel([...point,0],building),canvas=view.renderer3.domElement;
  const groups=()=>[view.groups.roof,view.groups.gableFull,view.groups.gableCut,view.groups.lights,...Object.values(view.groups.levels)]
    .flatMap(parent=>(parent?.children||[]).filter(g=>g.userData.buildingId===B));
  const transforms=()=>groups().map(g=>[g.position.toArray(),g.rotation.toArray()]);
  const before=transforms(),planBefore=JSON.stringify(flat);
  assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false);
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);
  assert.ok(lot.dragging());assert.notDeepEqual(transforms(),before);
  assert.ok(doc.getElementById('editor-drag-outline').getAttribute('points'));
  escape();await tick();
  assert.equal(lot.dragging(),false);assert.deepEqual(transforms(),before);
  assert.equal(doc.getElementById('editor-drag-outline').getAttribute('points'),'');
  assert.equal(doc.getElementById('editor-drag-hint').hidden,true);
  assert.equal(view.controls.enabled,true);assert.equal(canvas.hasPointerCapture(1),false);
  assert.equal(tools.selection().id,B,'cancel keeps selection');
  fire('pointerup',[p[0]+40,p[1]]);await tick();assert.equal(ops.length,0);assert.equal(JSON.stringify(flat),planBefore);
  fire('pointerdown',p);assert.ok(lot.dragging(),'a fresh press works after cancel');fire('pointercancel',p);
});
await test('esc_cancels_yard_object_drag',async({view,tools,ops,look,pixel,fire,click})=>{
  look([200,200,0]);tools.setTool('move');const p=pixel([200,200,0]);click(p);
  const outline=view.scene.children.find(o=>o instanceof THREE.Box3Helper),before=outline.box.clone(),planBefore=JSON.stringify(flat);
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);assert.equal(outline.box.equals(before),false);
  escape();await tick();
  assert.ok(outline.visible);assert.ok(outline.box.equals(before),'yard preview returns to its original location');
  assert.equal(tools.selection().id,'tree:gesture');assert.equal(view.controls.enabled,true);
  assert.equal(view.renderer3.domElement.hasPointerCapture(1),false);
  assert.equal(doc.getElementById('editor-drag-outline').getAttribute('points'),'');
  assert.equal(doc.getElementById('editor-drag-hint').hidden,true);
  fire('pointermove',[p[0]+70,p[1]]);fire('pointerup',[p[0]+70,p[1]]);await tick();
  assert.equal(ops.length,0);assert.equal(JSON.stringify(flat),planBefore);assert.ok(outline.box.equals(before));
});
await test('esc_cancels_pad_vertex_drag',async({view,tools,terrain,ops,look,fire})=>{
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  look([200,200,0]);terrain.choose('terraces','pad:gesture');
  const original=structuredClone(flat.site.terraces[0].polygon),p=terrain.handles()[0].screen;
  fire('pointerdown',p);fire('pointermove',[p[0]+30,p[1]]);
  assert.notDeepEqual(terrain.handles().filter(h=>!h.insert).map(h=>h.at),original);
  escape();await tick();
  assert.deepEqual(terrain.handles().filter(h=>!h.insert).map(h=>h.at),original,'cancel keeps the pad chosen and restores its preview');
  assert.deepEqual(flat.site.terraces[0].polygon,original);assert.equal(ops.length,0);
  assert.equal(view.controls.enabled,true);assert.equal(view.renderer3.domElement.hasPointerCapture(1),false);
  fire('pointerup',[p[0]+30,p[1]]);await tick();assert.equal(ops.length,0,'no update_pad after Esc');
  fire('pointerdown',p);assert.equal(view.controls.enabled,false,'arbiter accepts the next press');fire('pointercancel',p);
  escape();assert.equal(terrain.handles().length,0,'idle Esc still closes the ground card');assert.equal(tools.selection().id,null);
});
await test('esc_without_drag_goes_back',async({view,tools,ready})=>{
  const room=building.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7');
  view.setView(B+':L1');tools.select({kind:'room',id:room.id,building:B});await ready();
  const boundary=tools.selection().tinted.walls[0];assert.ok(boundary);
  tools.select({kind:'wall',id:boundary,building:B});assert.equal(tools.selection().room,room.id);
  escape();assert.equal(tools.selection().id,room.id);assert.equal(tools.selection().room,room.id);
  escape();assert.equal(tools.selection().id,null);assert.equal(tools.selection().room,null);
});
await test('esc_during_armed_pad_press_keeps_the_tools_own_cancel',async({view,terrain,ops,look,pixel,fire})=>{
  look([200,200,0]);terrain.startDrawing('terraces');const p=pixel([200,200,0]);
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);escape();
  assert.equal(view.controls.enabled,true);assert.equal(view.renderer3.domElement.hasPointerCapture(1),false);
  fire('pointerup',p);assert.equal(ops.length,0);
  fire('pointerdown',p);assert.equal(view.controls.enabled,true,'Esc exited drawing, so the next press navigates');
  fire('pointerup',p);
});
await test('esc_restores_pre_disabled_controls_for_handles_and_bodies',async({view,tools,terrain,ops,look,pixel,fire,click,ready})=>{
  look([200,200,0]);tools.setTool('move');const p=pixel([200,200,0]);click(p);
  view.controls.enabled=false;fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);escape();fire('pointerup',[p[0]+40,p[1]]);
  assert.equal(view.controls.enabled,false);assert.equal(ops.length,0);assert.equal(tools.selection().id,'tree:gesture');
  view.controls.enabled=true;tools.setTool('select');tools.select(null);
  flat.site.terraces=[{id:'pad:gesture',polygon:[[200,200],[220,200],[220,220],[200,220]],height:0,blend:0}];
  terrain.choose('terraces','pad:gesture');const q=terrain.handles()[0].screen;
  view.controls.enabled=false;fire('pointerdown',q);fire('pointermove',[q[0]+30,q[1]]);escape();fire('pointerup',[q[0]+30,q[1]]);
  assert.equal(view.controls.enabled,false);assert.equal(ops.length,0);assert.equal(terrain.handles().length,8);
  terrain.cancel();view.controls.enabled=true;view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  const mid=wall.from.map((v,i)=>(v+wall.to[i])/2);look([...mid,0],building);const r=pixel([...mid,0],building);
  view.controls.enabled=false;fire('pointerdown',r);fire('pointermove',[r[0],r[1]+40]);assert.ok(tools.dragging());
  escape();fire('pointerup',[r[0],r[1]+40]);await tick();
  assert.equal(tools.dragging(),false);assert.equal(view.controls.enabled,false);assert.equal(ops.length,0);
  assert.equal(tools.selection().id,W);assert.equal(view.renderer3.domElement.hasPointerCapture(1),false);
});
await test('rotate_tool_needs_selection_first',async({view,tools,ops,controlStates,look,pixel,fire})=>{
  view.setView('ext');tools.setTool('rotate');
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building,40);
  const p=pixel([...point,0],building),before=JSON.stringify(flat);assert.equal(view.pick(...p)?.building,B);
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);assert.equal(view.controls.enabled,true);assert.equal(tools.selection().id,null);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,null);assert.ok(controlStates.every(Boolean));
    assert.equal(JSON.stringify(flat),before);
    await marquee(p);
  });
});
await test('move_tool_other_selection_does_not_grab_tree',async({view,tools,ops,controlStates,look,pixel,fire,click})=>{
  tools.select({kind:'building',id:B,building:B});tools.setTool('move');look([200,200,0]);
  const p=pixel([200,200,0]);
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,B);assert.ok(controlStates.every(Boolean));
    await marquee(p);
    click(p);assert.equal(tools.selection().id,'tree:gesture');assert.equal(view.controls.enabled,true);
  });
});
await test('move_and_rotate_do_not_grab_a_building_through_an_unselected_tree',async({view,tools,library,ops,controlStates,look,pixel,fire})=>{
  view.setView('ext');tools.select({kind:'building',id:B,building:B});
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building,40);
  const p=pixel([...point,0],building),hit=view.pick(...p);
  assert.equal(hit?.building,B);assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false);
  flat.site.planting.push({id:'tree:in-front',kind:'tree',at:[hit.point[0]/.3048,-hit.point[2]/.3048],height:hit.point[1]/.3048+2});
  try {
    assert.equal(library.pickSite(...p)?.id,'tree:in-front','real tree box is in front of the building body');
    await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
      for(const tool of ['move','rotate']) {
        tools.setTool(tool);
        assert.equal(view.controls.enabled,true);assert.equal(tools.selection().id,B);
        await orbit(p);
        assert.equal(ops.length,0);assert.equal(tools.selection().id,B);assert.ok(controlStates.every(Boolean));
      }
      for(const tool of ['move','rotate']) {
        tools.setTool(tool);await marquee(p);
      }
    });
  } finally {flat.site.planting.pop();}
});
await test('rotate_tool_yard_body_selects_but_never_moves',async({view,tools,ops,controlStates,look,pixel,fire,click})=>{
  tools.setTool('rotate');look([200,200,0]);const p=pixel([200,200,0]);
  click(p);assert.equal(tools.selection().id,'tree:gesture');
  assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false);
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,'tree:gesture');assert.ok(controlStates.every(Boolean));
    await marquee(p);
  });
});
await test('move_tool_jitter_selects_then_body_jitter_sends_nothing',async({view,tools,ops,look,pixel,fire})=>{
  tools.setTool('move');look([200,200,0]);const p=pixel([200,200,0]);
  for(let i=0;i<2;i++) {
    fire('pointerdown',p);fire('pointermove',[p[0]+2,p[1]]);fire('pointerup',[p[0]+2,p[1]]);
    assert.equal(ops.length,0);assert.equal(tools.selection().id,'tree:gesture');assert.equal(view.controls.enabled,true);
  }
});
await test('selected_room_body_does_not_move_with_select_tool',async({view,tools,ops,controlStates,look,pixel,fire,ready})=>{
  const room=building.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7');
  view.setView(B+':L1');tools.select({kind:'room',id:room.id,building:B});await ready();
  const centre=[0,1].map(i=>room.polygon.reduce((sum,p)=>sum+p[i],0)/room.polygon.length);
  look([...centre,0],building);
  const ps=room.polygon.flatMap(vertex=>[.3,.5,.7].map(t=>vertex.map((v,i)=>v*(1-t)+centre[i]*t)));
  const p=ps.map(point=>pixel([...point,0],building)).find(p=>view.pick(...p)?.id===room.id&&!tools.handleAt({clientX:p[0],clientY:p[1]}));
  assert.ok(p,'actual room floor away from drawn handles exists');
  await cameraBindings({view,tools,fire,ops},async({orbit,marquee})=>{
    await orbit(p);
    assert.equal(ops.length,0);assert.ok(controlStates.every(Boolean));assert.equal(tools.selection().id,room.id);
    await marquee(p);
  });
});
await test('site_source_keeps_occluded_hits_but_legacy_wrapper_respects_the_house',async({view,tools,library,look,pixel})=>{
  const mid=wall.from.map((v,i)=>(v+wall.to[i])/2), a=(building.rotation||0)*Math.PI/180, pos=building.position||[0,0];
  const at=[Math.cos(a)*mid[0]-Math.sin(a)*mid[1]+pos[0],Math.sin(a)*mid[0]+Math.cos(a)*mid[1]+pos[1]];
  flat.site.planting.push({id:'tree:behind-house',kind:'tree',at,height:1});
  try {
    look([...mid,0],building);const p=pixel([...mid,0],building);
    const site=library.siteHits(...p).find(h=>h.id==='tree:behind-house');assert.ok(site);
    assert.ok(view.pickAll(...p)[0].distance<site.distance);
    assert.equal(library.pickSite(...p),null);
    const picked=tools.pick(...p);assert.equal(picked?.building,B);assert.ok(picked.distance<site.distance);
  } finally {flat.site.planting.pop();}
});
await test('precision_shift_follows_each_site_rotate_move',async({tools,ops,look,pixel,fire})=>{
  tools.select({id:'bed:gesture',kind:'beds'});tools.setTool('rotate');look([200,200,0]);
  const h=tools.handles().find(h=>h.kind==='gizmo_turn');assert.ok(h);
  const centre=[200,200],a=h.at.slice(0,2).map((v,i)=>v-centre[i]),angle=22*Math.PI/180;
  const end=[centre[0]+Math.cos(angle)*a[0]-Math.sin(angle)*a[1],centre[1]+Math.sin(angle)*a[0]+Math.cos(angle)*a[1],h.at[2]];
  const start=pixel(h.at),p=pixel(end);fire('pointerdown',start,0,{shiftKey:true});
  fire('pointermove',p,0,{shiftKey:false});fire('pointerup',p);await tick();
  assert.equal(ops.length,1);assert.ok(Math.abs(ops[0].operation.rotation%15)<1e-6);
  fire('pointerdown',start);fire('pointermove',p,0,{shiftKey:true});fire('pointerup',p,0,{shiftKey:true});await tick();
  assert.equal(ops.length,2);assert.ok(Math.abs(ops[1].operation.rotation-22)<1e-6);
});
await test('precision_escape_inside_typed_input_restores_joint',async({view,tools,ops,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();look([...wall.from,0],building);
  const h=tools.handles().find(h=>h.kind==='joint'&&h.id===wall.joints[0]),p=pixel(h.at,building);
  const before=structuredClone(flat);
  const buffers=()=>{const result=[];view.groups.levels[B+':L1'].traverse(o=>{if(o.geometry?.attributes.position)result.push([...o.geometry.attributes.position.array]);});return result;};
  const beforeBuffers=buffers(),beforeHandles=tools.handles();
  fire('pointerdown',p);fire('pointermove',[p[0]-40,p[1]]);
  assert.notDeepEqual(buffers(),beforeBuffers);
  const key=new Event('keydown',{cancelable:true});Object.assign(key,{key:'4'});doc.dispatchEvent(key);
  const input=descendants(view.renderer3.domElement.parentElement).find(n=>n.className==='editor-typed-value'&&!n.hidden);
  assert.ok(input);assert.equal(input.value,'4');
  const oldClosest=doc.closest;doc.closest=()=>input;
  try{escape();}finally{doc.closest=oldClosest;}
  fire('pointerup',[p[0]-40,p[1]]);await tick();
  assert.equal(ops.length,0);assert.equal(view.controls.enabled,true);assert.equal(input.hidden,true);assert.deepEqual(flat,before);
  const restored=buffers();assert.equal(restored.length,beforeBuffers.length);
  // Inverse deformation rounds through Float32; the model and handles below remain exact.
  restored.forEach((values,i)=>{assert.equal(values.length,beforeBuffers[i].length);assert.ok(values.every((v,j)=>Math.abs(v-beforeBuffers[i][j])<1e-5));});
  assert.deepEqual(tools.handles(),beforeHandles);
});
const typeValue=text=>{for(const key of [...text,'Enter']){const event=new Event('keydown',{cancelable:true});Object.assign(event,{key});doc.dispatchEvent(event);}};
await test('precision_typed_joint_length_is_exact_along_press_direction',async({view,tools,ops,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();look([...wall.from,0],building);
  const h=tools.handles().find(h=>h.kind==='joint'&&h.id===wall.joints[0]),p=pixel(h.at,building);
  fire('pointerdown',p);fire('pointermove',pixel([h.at[0]-3,h.at[1]-4,h.at[2]],building));
  typeValue('1.23');await tick();fire('pointerup',p);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_joint');
  const to=ops[0].operation.to;
  assert.ok(Math.abs(to[0]-h.at[0]+1.23*3/5)<1e-5);assert.ok(Math.abs(to[1]-h.at[1]+1.23*4/5)<1e-5);
  assert.equal(view.controls.enabled,true);assert.equal(view.renderer3.domElement.hasPointerCapture(1),false);
});
await test('precision_typed_site_angle_and_factor_apply_from_press',async({tools,ops,look,pixel,fire})=>{
  tools.select({id:'bed:gesture',kind:'beds'});tools.setTool('rotate');look([200,200,0]);
  for(const [kind,value] of [['gizmo_turn','22'],['gizmo_scale','1.27']]) {
    tools.setTool(kind==='gizmo_turn'?'rotate':'scale');const h=tools.handles().find(h=>h.kind===kind),p=pixel(h.at);
    fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]+30]);typeValue(value);await tick();fire('pointerup',p);
  }
  assert.equal(ops.length,2);assert.equal(ops[0].operation.rotation,22);
  const points=ops[1].operation.polygon;assert.ok(Math.abs(points[1][0]-points[0][0]-20*1.27)<1e-6);
});
await test('precision_typed_building_turn_routes_through_arbiter',async({view,tools,lot,ops,look,pixel,fire})=>{
  view.setView('ext');tools.select({kind:'building',id:B,building:B});tools.setTool('rotate');
  look([...wall.from,0],building);
  const h=lot.lotHandles().find(h=>h.kind==='turn');assert.ok(h);
  fire('pointerdown',h.screen);fire('pointermove',[h.screen[0]+40,h.screen[1]+20]);typeValue('30');await tick();
  fire('pointerup',h.screen);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation[0].op,'rotate_building');
  assert.equal(ops[0].operation[0].rotation,((building.rotation||0)+30)%360);
  assert.equal(view.controls.enabled,true);assert.equal(lot.dragging(),false);
});
await test('precision_free_options_reach_external_handle_source',async({tools,fire})=>{
  const options=[];tools.delegate({handleSources:[{hit:()=>({}),begin:()=>true,pointerMove:(event,option)=>options.push(option),pointerUp(){}}]});
  fire('pointerdown',[10,10],0,{shiftKey:true});fire('pointermove',[40,20],0,{shiftKey:false});
  fire('pointermove',[50,30],0,{shiftKey:true});fire('pointerup',[50,30]);
  assert.deepEqual(options,[{free:false},{free:true}]);
});
await test('gizmo_of_selection_wins_over_unselected_tree',async({tools,library,ops,look,pixel,fire})=>{
  tools.select({id:'bed:gesture',kind:'beds'});tools.setTool('move');look([200,200,0]);
  const h=tools.handles().find(h=>h.kind==='gizmo_move_x'),p=pixel(h.at);
  flat.site.planting.push({id:'tree:over-gizmo',kind:'tree',height:12,at:h.at.slice(0,2)});
  try {
    assert.ok(library.siteHits(...p).some(p=>p.id==='tree:over-gizmo'));
    fire('pointerdown',p);fire('pointermove',pixel([h.at[0]+3.2,h.at[1],h.at[2]]));fire('pointerup',p);await tick();
    assert.equal(tools.selection().id,'bed:gesture');assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_site_item');assert.deepEqual(ops[0].operation.by,[3,0]);
  } finally {flat.site.planting.pop();}
});
await test('gizmo_escape_with_focused_entry_cancels_and_releases',async({view,tools,ops,look,pixel,fire})=>{
  tools.select({id:'tree:gesture',kind:'planting'});tools.setTool('move');look([200,200,0]);
  const h=tools.handles().find(h=>h.kind==='gizmo_move_y'),p=pixel(h.at),before=structuredClone(flat);
  fire('pointerdown',p);fire('pointermove',[p[0]+30,p[1]+30]);
  const key=new Event('keydown',{cancelable:true});Object.assign(key,{key:'4'});doc.dispatchEvent(key);
  const input=descendants(view.renderer3.domElement.parentElement).find(n=>n.className==='editor-typed-value'&&!n.hidden);assert.ok(input);
  const oldClosest=doc.closest;doc.closest=()=>input;try{escape();}finally{doc.closest=oldClosest;}
  fire('pointerup',p);await tick();assert.equal(ops.length,0);assert.equal(input.hidden,true);assert.equal(view.controls.enabled,true);assert.deepEqual(flat,before);
});
await test('selected_yard_body_snaps_frees_and_accepts_exact_length',async({view,tools,ops,look,pixel,fire})=>{
  tools.select({id:'tree:gesture',kind:'planting'});tools.setTool('move');look([200,200,0],null,40);
  // Offset from the centre square and arrows, still inside the tree's body.
  const start=[200.8,200.8,0],p=pixel(start);assert.equal(tools.handleAt({clientX:p[0],clientY:p[1]}),false);
  for(const free of [false,true]) {
    const end=pixel([204,200.8,0]);fire('pointerdown',p,0,{shiftKey:!free});fire('pointermove',end,0,{shiftKey:free});fire('pointerup',end,0,{shiftKey:free});await tick();
    assert.ok(Math.abs(ops.at(-1).operation.at[0]-(free?203.2:203))<1e-6);assert.equal(ops.at(-1).operation.at[1],200);
  }
  fire('pointerdown',p);fire('pointermove',pixel([203.8,204.8,0]));typeValue('1.23');await tick();fire('pointerup',p);await tick();
  const at=ops.at(-1).operation.at;assert.ok(Math.abs(at[0]-200-1.23*3/5)<1e-6);assert.ok(Math.abs(at[1]-200-1.23*4/5)<1e-6);assert.equal(ops.length,3);assert.equal(view.controls.enabled,true);
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]+30]);fire('pointermove',p);fire('pointerup',p);await tick();assert.equal(ops.length,3,'return to the press sends no body move');
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]+30]);const key=new Event('keydown',{cancelable:true});Object.assign(key,{key:'4'});doc.dispatchEvent(key);escape();fire('pointerup',p);await tick();assert.equal(ops.length,3);assert.equal(view.controls.enabled,true);
});
await test('mirrored_yard_object_keeps_picker_outline_and_gizmo',async({view,tools,library,look,pixel})=>{
  const plant=flat.site.planting[0];tools.select({id:plant.id,kind:'planting'});tools.setTool('move');look([200,200,0]);
  library.refresh();const outline=view.scene.children.find(o=>o.type==='Box3Helper'),box=outline.box.clone();
  const handles=structuredClone(tools.handles().filter(h=>h.kind.startsWith('gizmo_')));assert.equal(handles.length,3);
  try {
    plant.mirror_x=true;plant.mirror_y=true;tools.refresh();library.refresh();
    assert.ok(library.siteHits(...pixel([200,200,0])).some(h=>h.id===plant.id));
    assert.ok(outline.visible);assert.deepEqual(outline.box,box);assert.deepEqual(tools.handles().filter(h=>h.kind.startsWith('gizmo_')),handles);
    assert.equal(plant.scale,undefined);assert.equal(plant.scale_axes,undefined);
  } finally {delete plant.mirror_x;delete plant.mirror_y;}
});
await test('measure_toolbar_clicks_do_not_pick_or_move_and_escape_keeps_selection',async({view,tools,ops,look,pixel,fire,ready,ordinaryPresses,resizeCanvas})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  const middle=wall.from.map((v,i)=>(v+wall.to[i])/2);look([...middle,0],building);
  const selected=structuredClone(tools.selection());
  doc.getElementById('rail-measure').dispatchEvent(new Event('click'));
  const canvas=view.renderer3.domElement;
  const measureClick=p=>{fire('pointerdown',p);const event=new Event('pointerup');
    Object.assign(event,{button:0,pointerId:1,clientX:p[0],clientY:p[1]});canvas.dispatchEvent(event);};
  measureClick(pixel([...wall.from,0],building));measureClick(pixel([...wall.to,0],building));
  const labels=()=>descendants(canvas.parentElement).filter(n=>n.className==='editor-measure-label');
  assert.equal(labels().length,1);assert.ok(labels()[0].textContent.includes("'"));
  assert.deepEqual(tools.selection(),selected);assert.equal(ops.length,0);assert.equal(ordinaryPresses(),0);
  assert.equal(view.controls.enabled,true);escape();assert.equal(labels().length,0);
  assert.deepEqual(tools.selection(),selected);assert.equal(doc.getElementById('rail-select').getAttribute('aria-pressed'),'true');
  doc.getElementById('rail-measure').dispatchEvent(new Event('click'));
  measureClick(pixel([...wall.from,0],building));measureClick(pixel([...wall.to,0],building));
  assert.equal(labels().length,1);const oldLeft=labels()[0].style.left;
  canvas.getBoundingClientRect=()=>({left:80,top:120,width:1200,height:700,right:1280,bottom:820});
  view.camera.aspect=1200/700;view.camera.updateProjectionMatrix();resizeCanvas();
  assert.notEqual(labels()[0].style.left,oldLeft,'canvas resize reprojects through the current rect');
  tools.setTool('move');assert.equal(labels().length,0);assert.equal(ops.length,0);
});
await test('measure_exterior_uses_ground_coordinates_and_survives_camera_change',async({view,tools,ops,look,pixel,fire})=>{
  view.setView('ext');look([200,200,0]);tools.setTool('measure');
  const canvas=view.renderer3.domElement;
  for(const point of [[200,200,0],[203,204,0]]) {
    const p=pixel(point);fire('pointerdown',p);const event=new Event('pointerup');
    Object.assign(event,{button:0,pointerId:1,clientX:p[0],clientY:p[1]});canvas.dispatchEvent(event);
  }
  const label=()=>descendants(canvas.parentElement).find(n=>n.className==='editor-measure-label');
  assert.equal(label()?.textContent,`5'-0"`);const left=label().style.left;
  look([201,201,0]);view.controls.dispatchEvent({type:'change'});assert.notEqual(label().style.left,left);
  assert.equal(ops.length,0);tools.setTool('select');assert.equal(label(),undefined);
});
console.log(`${passed}/${passed+failed} passed`);if(failed)process.exitCode=1;
"""


def run():
    os.environ.pop('HA_BASE_URL', None)
    os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_gestures_'))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='gesture_events_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': flatten(assemble(fixture)[0]), 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=180)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
