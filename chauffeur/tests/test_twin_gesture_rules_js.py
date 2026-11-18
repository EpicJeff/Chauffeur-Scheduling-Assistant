"""Select-tool arbitration through real scene tools, library, handles and CPU rays.

No browser is started; OrbitControls is the existing CPU harness double.
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
const nodes = new Map(), doc = new Element();
Element.prototype.getAttribute = function(k) { return this[k]; };
Element.prototype.querySelectorAll = () => [];
Element.prototype.querySelector = () => null;
Element.prototype.setPointerCapture = function(id) { this.capture = id; };
Element.prototype.hasPointerCapture = function(id) { return this.capture === id; };
Element.prototype.releasePointerCapture = function() { this.capture = null; };
doc.createElement = () => new Element();
doc.getElementById = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
doc.querySelector = () => null; doc.querySelectorAll = () => []; globalThis.document = doc;
window.showGlobalAlert = message => { throw Error(message); };
globalThis.fetch = async () => new Response(JSON.stringify({limit_mb:50,unpacked_limit_mb:200,entries:{},revision:1,materials:[],items:[],imports:[]}));
flat.site = {planting:[{id:'tree:gesture',kind:'tree',at:[200,200],height:10}],
  beds:[{id:'bed:gesture',polygon:[[190,190],[210,190],[210,210],[190,210]]}]};
const B='pool-house', W='wall:9adea4c38eb2430697cf47d4ddee9d2a';
const building=flat.buildings.find(b=>b.id===B), wall=building.walls.find(w=>w.id===W);
let passed=0, failed=0;
const tick=()=>new Promise(r=>setTimeout(r,0));
async function test(name, body) {
  const view=await mountTwin(new Element(),{plan:flat,kit,tier:'low',preserveCamera:true});
  const abort=new AbortController(), ops=[], controlStates=[];
  let library, enabled=true, writable=true;
  Object.defineProperty(view.controls,'enabled',{get:()=>enabled,set:value=>{enabled=value;controlStates.push(value);}});
  const op=async(operation,options)=>ops.push({operation,options});
  const tools=createSceneTools({view,getPlan:()=>flat,getModel:()=>flat,getKit:()=>kit,getSheets:()=>({}),op,edit:op,
    panel:{clearSelection(){},focusSelection(){}},canEdit:()=>writable,signal:abort.signal,
    siteHits:(x,y)=>library?.siteHits(x,y) || [],pickSite:(x,y)=>library?.pickSite(x,y)});
  library=createLibrary({view,kit,getPlan:()=>flat,tools,op,canEdit:()=>true,signal:abort.signal});
  tools.delegate({pointerDown:library.pointerDown,pointerMove:library.pointerMove,pointerUp:library.pointerUp,selectionChanged:library.refresh});
  const canvas=view.renderer3.domElement;
  const world=(p,b=null)=>{
    const angle=(b?.rotation||0)*Math.PI/180, pos=b?.position||[0,0];
    return new THREE.Vector3((Math.cos(angle)*p[0]-Math.sin(angle)*p[1]+pos[0])*.3048,
      ((p[2]||0)+(b?.base||0))*.3048,-(Math.sin(angle)*p[0]+Math.cos(angle)*p[1]+pos[1])*.3048);
  };
  const look=(point,b=null)=>view.setCameraState({position:world([point[0],point[1]-.01,150],b).toArray(),target:world(point,b).toArray()});
  const pixel=(point,b=null)=>{const p=world(point,b).project(view.camera);return [(p.x+1)*720,(1-p.y)*450];};
  function fire(type,p,button=0,extra={}) {
    const event=new Event(type);Object.assign(event,{pointerId:1,button,buttons:type==='pointerdown'?1:0,clientX:p[0],clientY:p[1],...extra});
    (type==='pointerup'?doc:canvas).dispatchEvent(event);
  }
  const click=p=>{fire('pointerdown',p);fire('pointerup',p);};
  const ready=async()=>{while(!view.ready)await tick();};
  try {await body({view,tools,library,ops,controlStates,look,pixel,fire,click,ready,setWritable:value=>writable=value});passed++;console.log('  ok '+name);}
  catch(error){failed++;console.error('  FAIL '+name+'\n'+error.stack);}
  finally {abort.abort();await tick();view.dispose();}
}
await test('unselected_press_navigates',async({view,tools,ops,controlStates,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]), before=JSON.stringify(flat);
  fire('pointerdown',p);assert.equal(tools.selection().id,null);assert.equal(view.controls.enabled,true);
  fire('pointermove',[p[0]+40,p[1]]);assert.equal(view.controls.enabled,true);
  fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,0);assert.equal(tools.selection().id,null);
  assert.ok(controlStates.every(Boolean));assert.equal(JSON.stringify(flat),before);
});
await test('jitter_under_threshold_is_a_click',async({tools,ops,look,pixel,fire})=>{
  look([200,200,0]);const p=pixel([200,200,0]);
  fire('pointerdown',p);fire('pointermove',[p[0]+2,p[1]]);fire('pointerup',[p[0]+2,p[1]]);await tick();
  assert.equal(tools.selection().id,'tree:gesture');assert.equal(ops.length,0);
});
await test('selected_wall_body_does_not_move_with_select_tool',async({view,tools,ops,controlStates,look,pixel,fire,ready})=>{
  view.setView(B+':L1');tools.select({kind:'wall',id:W,building:B});await ready();
  const point=wall.from.map((v,i)=>v*.8+wall.to[i]*.2);look([...point,0],building);
  const p=pixel([...point,0],building);
  assert.equal(view.pick(...p)?.id,W,'press is on the actual wall');
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,0);assert.ok(controlStates.every(Boolean));assert.equal(view.controls.enabled,true);
  assert.equal(tools.selection().id,W);
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
await test('move_tool_keeps_yard_body_move_available',async({view,tools,ops,look,pixel,fire})=>{
  look([200,200,0]);tools.setTool('move');const p=pixel([200,200,0]);
  fire('pointerdown',p);assert.equal(view.controls.enabled,false);
  fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,1);assert.equal(ops[0].operation.op,'move_site_item');assert.equal(ops[0].options.drag,true);
  assert.equal(view.controls.enabled,true);
});
await test('selected_room_body_does_not_move_with_select_tool',async({view,tools,ops,controlStates,look,pixel,fire,ready})=>{
  const room=building.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7');
  view.setView(B+':L1');tools.select({kind:'room',id:room.id,building:B});await ready();
  const centre=[0,1].map(i=>room.polygon.reduce((sum,p)=>sum+p[i],0)/room.polygon.length);
  look([...centre,0],building);
  const ps=room.polygon.flatMap(vertex=>[.3,.5,.7].map(t=>vertex.map((v,i)=>v*(1-t)+centre[i]*t)));
  const p=ps.map(point=>pixel([...point,0],building)).find(p=>view.pick(...p)?.id===room.id&&!tools.handleAt({clientX:p[0],clientY:p[1]}));
  assert.ok(p,'actual room floor away from drawn handles exists');
  fire('pointerdown',p);fire('pointermove',[p[0]+40,p[1]]);fire('pointerup',[p[0]+40,p[1]]);await tick();
  assert.equal(ops.length,0);assert.ok(controlStates.every(Boolean));assert.equal(tools.selection().id,room.id);
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
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
