"""Task 4: execute the real cards, camera-ray handles and Check queue in Node.

No browser is launched. The companion Chromium scenario is run by Claude.
"""
import os
from pathlib import Path
import sys
import tempfile

os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='gutters_editor_')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from twin_editor_dom import PRELUDE, run_node
from test_twin_gutters_model import house
from services.twin_model_bridge import flatten

DRIVER = PRELUDE + r"""
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {gutterRuns,downspouts}=await import(file('static/twin/gutters.js'));
const THREE=await import(three);
const original=input.plan;
let plan, cards, ops, enabled, confirmAnswer, confirms;
window.showGlobalAlert=message=>{throw Error(message);};
window.promptConfirm=async (...args)=>{confirms.push(args);return confirmAnswer;};
const host=document.getElementById('piece-card');
const roof=()=>plan.buildings[0].roofs[0];
function setup(){
  plan=structuredClone(original); ops=[]; enabled=true; confirms=[];confirmAnswer=true;
  cards=createCards({getPlan:()=>plan,getLabel:()=> 'Roof',getKit:()=>({}),
    canEdit:()=>enabled,edit:()=>{},op:async operation=>{ops.push(operation);},select(){},ask(){}});
}
const edge=i=>cards.showRoofEdge({id:'r',building:'b',edge:i});
const roofCard=()=>cards.draw({pieceId:'r',buildingId:'b'});
const control=label=>host.querySelector(`[aria-label="${label}"]`);
const button=text=>host.querySelectorAll('button').find(n=>n.textContent===text);
async function press(text){const node=button(text);assert.ok(node,`missing ${text}`);assert.equal(node.disabled,false);click(node);await tick();await cards.queue(()=>{});await tick();}
async function toggle(){const node=control('Gutter');assert.ok(node,'Gutter checkbox is present');node.checked=!node.checked;fire(node,'change');await tick();await cards.queue(()=>{});await tick();}
function spouts(){const runs=gutterRuns(plan);return downspouts(plan,runs);}
function handleRig(){
  const canvas=document.createElement('canvas');document.body.append(canvas);
  const camera=new THREE.PerspectiveCamera(45,1440/900,.01,1000);
  const b=plan.buildings[0], a=(b.rotation||0)*Math.PI/180;
  const world=p=>new THREE.Vector3(((b.position?.[0]||0)+Math.cos(a)*p[0]-Math.sin(a)*p[1])*.3048,
    (p[2]+(b.base||0))*.3048,-((b.position?.[1]||0)+Math.sin(a)*p[0]+Math.cos(a)*p[1])*.3048);
  camera.position.copy(world([20,14.99,110]));camera.lookAt(world([20,15,10]));camera.updateMatrixWorld(true);
  const view={renderer3:{domElement:canvas},camera,controls:new THREE.EventDispatcher(),groups:{levels:{}},pick:()=>null};
  const abort=new AbortController();
  const handles=createHandles({view,getPlan:()=>plan,getSelection:()=>({kind:'roof',id:'r',building:'b'}),
    canEdit:()=>enabled,drag:{},onCommit:async operation=>ops.push(operation),signal:abort.signal});
  const event=p=>{const v=world(p).project(camera);return {clientX:(v.x+1)*720,clientY:(1-v.y)*450};};
  return {handles,event,abort,canvas};
}
await test('test_gutter_toggle_only_on_eave_edges',async()=>{
  setup();edge(0);assert.ok(control('Gutter'));await toggle();assert.deepEqual(ops,[{op:'set_roof_edge',building:'b',roof:'r',edge:0,gutter:true}]);
  for(const setting of ['gable','clip']){setup();roof().edges[0].setting=setting;edge(0);assert.equal(control('Gutter'),null);}
  setup();const section=plan.buildings[0].roof.sections[0];section.kind='shed';section.low_side='y0';
  edge(section.plane_edges.y0);assert.ok(control('Gutter'),'shed low edge is an eave');
  edge(section.plane_edges.y1);assert.equal(control('Gutter'),null,'shed high edge has no eave even when authored sloped');
});
await test('test_all_eaves_is_one_batch',async()=>{
  setup();roof().edges[1].setting='gable';roofCard();await press('Gutters on all eaves');
  assert.equal(ops.length,1);assert.equal(ops[0].op,'batch');assert.deepEqual(ops[0].ops.map(o=>o.edge),[0,2,3]);
  assert.ok(ops[0].ops.every(o=>o.op==='set_roof_edge'&&o.gutter===true&&o.roof==='r'&&o.building==='b'));
});
await test('test_remove_all_is_one_batch',async()=>{
  setup();roof().edges.forEach(e=>e.gutter=true);roofCard();await press('Remove all gutters');
  assert.equal(ops.length,1);assert.equal(ops[0].op,'batch');assert.equal(ops[0].ops.length,4);
  assert.ok(ops[0].ops.every(o=>o.op==='set_roof_edge'&&o.gutter===false));
});
await test('test_rake_switch_on_guttered_edge_confirms_and_batches',async()=>{
  for(const setting of ['gable','clip'])for(const yes of [true,false]){
    setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.2,.8];confirmAnswer=yes;edge(0);
    await press(setting==='gable'?'Gable':'Clipped');assert.equal(confirms.length,1);
    assert.match(confirms[0].join(' '),/gutter.*downspout overrides/i);
    assert.equal(ops.length,yes?1:0);
    if(yes)assert.deepEqual(ops[0],{op:'batch',ops:[
      {op:'set_roof_edge',building:'b',roof:'r',edge:0,gutter:false,downspouts:null},
      {op:'set_roof_edge',building:'b',roof:'r',edge:0,setting}]});
  }
});
await test('test_drag_writes_fraction_override',async()=>{
  const g=await import(file('static/twin/gutters.js'));
  setup();roof().edges[0].gutter=true;
  // Exercise rotation and translation, not just axis-aligned screen coordinates.
  plan.buildings[0].rotation=31;plan.buildings[0].position=[7,-4];
  g._gutterPlacementStats.clearCache();
  const rig=handleRig();try{
    const h=rig.handles.handles().find(h=>h.kind==='downspout');assert.ok(h,'generated downspout handle');
    const actual=spouts()[0], b=plan.buildings[0], a=-b.rotation*Math.PI/180;
    const x=actual.top[0]/.3048-b.position[0],y=-actual.top[2]/.3048-b.position[1];
    assert.ok(Math.hypot(h.at[0]-(Math.cos(a)*x-Math.sin(a)*y),h.at[1]-(Math.sin(a)*x+Math.cos(a)*y))<1e-6);
    const beforeCalls=g._gutterPlacementStats.calls;
    assert.ok(rig.handles.begin(rig.event(h.at)));
    const from=roof().area[0],to=roof().area[1];
    // Multiple moves across the edge must not rebuild placement during the drag.
    for(let i=1;i<=10;i++){
      const f=.2+.045*i, pt=[from[0]+f*(to[0]-from[0]),from[1]+f*(to[1]-from[1]),h.at[2]];
      rig.handles.update(rig.event(pt));
    }
    assert.equal(g._gutterPlacementStats.calls-beforeCalls,0,'placement does not rebuild during drag');
    const target=[from[0]+.65*(to[0]-from[0]),from[1]+.65*(to[1]-from[1]),h.at[2]];
    rig.handles.update(rig.event(target));assert.equal(ops.length,0);await rig.handles.finish();
    assert.equal(ops.length,1);assert.equal(ops[0].op,'set_roof_edge');assert.equal(ops[0].edge,0);
    assert.ok(ops[0].downspouts.some(t=>t&&typeof t==='object'&&Math.abs(t.at-.65)<.002&&Object.keys(t).length===1),JSON.stringify(ops));
  }finally{rig.abort.abort();}
});
await test('test_snap_inside_1ft_and_exact_outside',async()=>{
  const {snapOrExact,entryFraction,isExact}=await import(file('static/twin/editor/gutter_controls.js'));
  const g=await import(file('static/twin/gutters.js'));
  setup();roof().edges[0].gutter=true;g._gutterPlacementStats.clearCache();
  // Edge 0 is 40 ft long with safe corner candidates at 0 and 1.
  // 0.8 ft from corner 0 (f=0.02) snaps to number 0; 1.2 ft (f=0.03) stays exact {at: 0.03}.
  const snappedLo=snapOrExact(plan,'b','r',0,0.8/40);
  assert.equal(typeof snappedLo,'number');assert.ok(Math.abs(snappedLo-0)<1e-6);
  const snappedHi=snapOrExact(plan,'b','r',0,1-0.9/40);
  assert.equal(typeof snappedHi,'number');assert.ok(Math.abs(snappedHi-1)<1e-6);
  const exactMid=snapOrExact(plan,'b','r',0,1.2/40);
  assert.equal(isExact(exactMid),true);assert.deepEqual(Object.keys(exactMid),['at']);
  assert.ok(Math.abs(entryFraction(exactMid)-1.2/40)<1e-9);
  assert.equal(g._gutterPlacementStats.calls,1,'snapOrExact uses cached placement');
  // Real drag within 1 ft of a FREE corner jumps the handle to that candidate's real drip position and commits a number.
  // First verify with only corner 0 occupied (corner 1 free).
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0];g._gutterPlacementStats.clearCache();
  const rig=handleRig();try{
    const h=rig.handles.handles().find(h=>h.kind==='downspout');assert.ok(h);
    const from=roof().area[0],to=roof().area[1],nearEnd=[from[0]+(1-0.5/40)*(to[0]-from[0]),from[1]+(1-0.5/40)*(to[1]-from[1]),h.at[2]];
    const callsBefore=g._gutterPlacementStats.calls;
    assert.ok(rig.handles.begin(rig.event(h.at)));
    rig.handles.update(rig.event(nearEnd));
    assert.equal(g._gutterPlacementStats.calls,callsBefore,'no placement rebuild during snap drag');
    const moved=rig.handles.handles().find(x=>x.spout===h.spout);
    // Perpendicular offset (gutter drip line) is preserved; X jumps to corner 1's drip position.
    assert.ok(Math.abs(moved.at[1]-h.at[1])<1e-5,'handle stays on gutter drip line, not roof-area line');
    assert.ok(moved.at[0]>to[0]&&Math.abs(moved.at[0]-(to[0]+(from[0]-h.at[0])))<.02,
      `handle jumps to corner 1 real drip position: ${JSON.stringify(moved.at)}`);
    await rig.handles.finish();
    assert.equal(ops.length,1);
    assert.ok(ops[0].downspouts.some(v=>typeof v==='number'&&Math.abs(v-1)<1e-5),JSON.stringify(ops));
  }finally{rig.abort.abort();}
  // Dragging within 1 ft of a corner already used by ANOTHER entry stores {at: f}, never two on one corner.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,1];
  const occRig=handleRig();try{
    const h0=occRig.handles.handles().find(h=>h.kind==='downspout'&&h.at[0]<20);assert.ok(h0);
    const from=roof().area[0],to=roof().area[1],nearOccupied=[from[0]+(1-0.5/40)*(to[0]-from[0]),from[1]+(1-0.5/40)*(to[1]-from[1]),h0.at[2]];
    assert.ok(occRig.handles.begin(occRig.event(h0.at)));
    occRig.handles.update(occRig.event(nearOccupied));
    await occRig.handles.finish();
    assert.equal(ops.length,1);
    const entry=ops[0].downspouts[0];
    assert.ok(entry&&typeof entry==='object'&&'at' in entry,'occupied corner stores {at: f} instead of duplicating corner');
    assert.equal(entry.at,Math.round(entry.at*1e4)/1e4,'{at} rounded to 1e-4');
  }finally{occRig.abort.abort();}
});
await test('test_overhang_2_end_preview_occupied_stub_and_merged_corner_noop',async()=>{
  // N2: at overhang 2, dragging past an occupied corner previews at the exposed end past the vertex (42, not 40).
  setup();roof().overhang=2;plan.buildings[0].roof.sections[0].overhang=2;
  roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,1];
  const rig=handleRig();try{
    const h0=rig.handles.handles().find(h=>h.kind==='downspout'&&h.at[0]<20);assert.ok(h0);
    assert.ok(Math.abs(h0.at[0]-(-2))<.05,`overhang 2 puts corner 0 at x=-2, got ${h0.at[0]}`);
    const pastEnd=[42,h0.at[1],h0.at[2]];
    assert.ok(rig.handles.begin(rig.event(h0.at)));
    rig.handles.update(rig.event(pastEnd));
    const moved=rig.handles.handles().find(x=>x.spout===h0.spout);
    assert.ok(Math.abs(moved.at[0]-42)<.05,`exact 1 preview uses exposed end at 42, got ${moved.at[0]}`);
    await rig.handles.finish();
    assert.equal(ops.length,1);assert.deepEqual(ops[0].downspouts[0],{at:1});
  }finally{rig.abort.abort();}
  // N2: at overhang 2, a 4 px move on a stub at corner 0 keeps preview at x=-2 (does not jump inward to 0).
  setup();roof().overhang=2;plan.buildings[0].roof.sections[0].overhang=2;
  roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];
  const stubRig=handleRig();try{
    const stub=spouts().find(s=>s.mount==='hang'&&s.flags.includes('stub')&&s.edge.fraction<.5);assert.ok(stub);
    const h=stubRig.handles.handles().find(x=>x.spout===stub.id);assert.ok(h);
    assert.ok(Math.abs(h.at[0]-(-2))<.05,`stub at overhang 2 starts at x=-2, got ${h.at[0]}`);
    const baseEv=stubRig.event(h.at);
    assert.ok(stubRig.handles.begin(baseEv));
    stubRig.handles.update({clientX:baseEv.clientX+4,clientY:baseEv.clientY});
    const moved=stubRig.handles.handles().find(x=>x.spout===h.spout);
    assert.ok(Math.abs(moved.at[0]-(-2))<.05,`4 px move on overhang-2 stub stays at x=-2, got ${moved.at[0]}`);
    await stubRig.handles.finish();
  }finally{stubRig.abort.abort();}
  // N3: [.2, .3] both drawn at corner 0 -> a 4 px move commits nothing.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.2,.3];
  const mergedRig=handleRig();try{
    const h=mergedRig.handles.handles().find(h=>h.kind==='downspout');assert.ok(h);
    const baseEv=mergedRig.event(h.at);
    assert.ok(mergedRig.handles.begin(baseEv));
    mergedRig.handles.update({clientX:baseEv.clientX+4,clientY:baseEv.clientY});
    await mergedRig.handles.finish();
    assert.equal(ops.length,0,'4 px move on [.2,.3] at corner 0 commits nothing');
  }finally{mergedRig.abort.abort();}
});
await test('test_drag_off_centre_grab_and_noop_commit',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[{at:.5}];
  const rig=handleRig();try{
    const from=roof().area[0],to=roof().area[1];
    // Use real spout at corner 0 for off-centre grab test (unmerged gutters.js places corners).
    roof().edges[0].downspouts=[0];
    const h=rig.handles.handles().find(x=>x.kind==='downspout');assert.ok(h);
    const baseEv=rig.event(h.at);
    // Grab 14 px to the right of the handle centre, then move only 4 px further right.
    const grabEv={clientX:baseEv.clientX+14,clientY:baseEv.clientY};
    const moveEv={clientX:baseEv.clientX+18,clientY:baseEv.clientY};
    assert.ok(rig.handles.begin(grabEv),'14 px off-centre grab hits handle');
    // Measure world move of 4 px vs 18 px from handle centre.
    rig.handles.update(moveEv);
    const after4px=rig.handles.handles().find(x=>x.spout===h.spout);
    // 4 px at height 100 ft is ~0.37 ft (< 1 ft from corner 0), whereas 18 px is ~1.67 ft (> 1 ft).
    // With grab offset preserved, a 4 px move stays snapped to corner 0 and commits nothing!
    await rig.handles.finish();
    assert.equal(ops.length,0,'4 px move from 14 px off-centre grab stays at corner 0 and commits nothing');
    // Now move 25 px from the 14 px off-centre grab (25 px > 1 ft, so moves ~2.3 ft, NOT ~3.6 ft).
    const farEv={clientX:baseEv.clientX+39,clientY:baseEv.clientY};
    assert.ok(rig.handles.begin(grabEv));
    rig.handles.update(farEv);
    const moved=rig.handles.handles().find(x=>x.spout===h.spout);
    assert.ok(Math.abs(moved.at[1]-h.at[1])<1e-5,'gutter perpendicular offset preserved during free drag');
    await rig.handles.finish();
    assert.equal(ops.length,1);
    const atVal=ops[0].downspouts[0].at;
    assert.ok(typeof atVal==='number'&&atVal>0.03&&atVal<0.08,`expected ~2.3 ft (~0.058), got ${atVal}`);
    assert.equal(atVal,Math.round(atVal*1e4)/1e4,'{at} rounded to 1e-4');
  }finally{rig.abort.abort();}
});
await test('test_drag_on_rotated_roof_frame',async()=>{
  setup();roof().edges[0].gutter=true;
  const frame={origin:[20,15],angle:Math.PI/6};
  roof().roof_frame=frame;
  plan.buildings[0].roof.sections[0].roof_frame=frame;
  const {roofEdge}=await import(file('static/twin/editor/roof_tools.js'));
  const rig=handleRig();try{
    const h=rig.handles.handles().find(x=>x.kind==='downspout');assert.ok(h,'rotated roof has downspout handle');
    const {a,b}=roofEdge(roof(),h.edge);
    assert.ok(rig.handles.begin(rig.event(h.at)));
    const mid=[a[0]+.6*(b[0]-a[0]),a[1]+.6*(b[1]-a[1]),h.at[2]];
    rig.handles.update(rig.event(mid));
    await rig.handles.finish();
    assert.equal(ops.length,1);
    assert.ok(ops[0].downspouts.some(v=>v&&typeof v==='object'&&Math.abs(v.at-.6)<.005&&v.at===Math.round(v.at*1e4)/1e4),JSON.stringify(ops));
  }finally{rig.abort.abort();}
});
await test('test_stub_drag_stores_exact_override',async()=>{
  setup();roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];
  const stub=spouts().find(s=>s.mount==='hang'&&s.flags.includes('stub'));
  assert.ok(stub,'fixture produces a real hang/stub spout');
  const rig=handleRig();try{
    const h=rig.handles.handles().find(x=>x.spout===stub.id);assert.ok(h,'stub has a draggable handle');
    assert.ok(rig.handles.begin(rig.event(h.at)));
    const from=roof().area[0],to=roof().area[1],mid=[from[0]+.45*(to[0]-from[0]),from[1]+.45*(to[1]-from[1]),h.at[2]];
    rig.handles.update(rig.event(mid));assert.equal(ops.length,0);await rig.handles.finish();
    assert.equal(ops.length,1);assert.equal(ops[0].op,'set_roof_edge');
    assert.ok(ops[0].downspouts.some(v=>v&&typeof v==='object'&&Math.abs(v.at-.45)<.005),JSON.stringify(ops));
  }finally{rig.abort.abort();}
});
await test('test_right_click_removes_one',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.1,.9];
  const rig=handleRig();try{
    const h=rig.handles.handles().find(h=>h.kind==='downspout');assert.ok(h);
    const ev=rig.event(h.at);assert.equal(await rig.handles.removeAt(ev),true);
    assert.equal(ops.length,1);assert.equal(ops[0].op,'set_roof_edge');assert.equal(ops[0].downspouts.length,1);
    assert.ok([.1,.9].includes(ops[0].downspouts[0]));
    enabled=false;assert.equal(await rig.handles.removeAt(ev),false);assert.equal(ops.length,1);
  }finally{rig.abort.abort();}
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.8,.9];
  const mergedRig=handleRig();try{
    const spout=spouts()[0];assert.equal(spouts().length,1,'both requests snap to one visible corner');
    const h=mergedRig.handles.handles().find(h=>h.spout===spout.id);assert.ok(h);
    await mergedRig.handles.removeAt(mergedRig.event(h.at));
    assert.deepEqual(ops[0].downspouts,[.9],'remove the winning override; preserve the merged request');
  }finally{mergedRig.abort.abort();}
});
await test('test_add_disabled_at_8_and_fallback_on_no_free_corner',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=Array.from({length:8},(_,i)=>i/7);edge(0);
  const add=button('Add downspout');assert.ok(add);assert.equal(add.disabled,true);
  cards.draw();assert.equal(button('Add downspout').disabled,true,'poll keeps capacity disabled');
  // Free safe corner is used first when available.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0];edge(0);await press('Add downspout');
  assert.equal(ops.length,1);assert.equal(ops[0].downspouts.length,2);assert.ok(ops[0].downspouts[1]>.9,'adds the other free corner');
  assert.ok(ops[0].downspouts.every(t=>typeof t==='number'&&t>=0&&t<=1));
  // With no free safe corner (both corners already occupied), Add falls back to {at: middle of longest exposed piece}.
  setup();roof().edges[0].gutter=true;edge(0);
  assert.equal(button('Add downspout').disabled,false,'fallback enables Add when exposed edge has room');
  await press('Add downspout');
  assert.equal(ops.length,1,'add is one operation');
  const added=ops[0].downspouts.at(-1);
  assert.ok(added&&typeof added==='object'&&Math.abs(added.at-.5)<1e-4&&Object.keys(added).length===1,JSON.stringify(ops[0].downspouts));
  // Calling Add again when midpoint 0.5 is already taken picks a clear span at least 1 ft away.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,1,{at:.5}];edge(0);await press('Add downspout');
  assert.equal(ops.length,1);const second=ops[0].downspouts.at(-1);
  assert.ok(second&&typeof second==='object'&&Math.abs(second.at-.25)<.02,JSON.stringify(ops[0].downspouts));
  // Disabled when no point on the exposed edge is >= 1 ft from existing entries (1.5 ft edge with spout at 0.5).
  setup();roof().edges[0].gutter=true;
  roof().area=[[0,0],[1.5,0],[1.5,10],[0,10]];
  plan.buildings[0].levels[0].outline=[[0,0],[1.5,0],[1.5,10],[0,10]];
  plan.buildings[0].roof.sections[0].rect=[0,0,1.5,10];
  roof().edges[0].downspouts=[{at:.5}];edge(0);
  assert.equal(button('Add downspout').disabled,true,'disabled when no place >= 1 ft from existing entries');
});
await test('test_add_omits_only_automatic_stubs_and_keeps_row_and_handle_until_add',async()=>{
 setup();roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];
 const C=await import(file('static/twin/editor/gutter_controls.js'));
 const before=spouts();assert.ok(before.length);assert.ok(before.every(s=>s.flags.includes('stub')));
 assert.deepEqual(C.downspoutValues(plan,'b','r',0),before.map(s=>s.edge.fraction),'stubs remain available to their rows and drag');
 edge(0);assert.equal(host.querySelectorAll('[data-downspout-row]').length,before.length);
 const rig=handleRig();try{assert.ok(rig.handles.handles().some(h=>h.kind==='downspout'&&h.spout===before[0].id));}
 finally{rig.abort.abort();}
 await press('Add downspout');assert.deepEqual(ops[0].downspouts,[{at:.5}]);
 plan=structuredClone(plan);roof().edges[0].downspouts=ops[0].downspouts;
 assert.equal(spouts().length,1);assert.equal(spouts()[0].exact,true);assert.ok(!spouts()[0].flags.includes('stub'));
 // Explicitly authored requests remain, even when their current result is a stub.
 roof().edges[0].downspouts=[0];assert.deepEqual(C.addDownspout(plan,'b','r',0),[0,{at:.5}]);
});
await test('test_exact_rounding_preserves_interior_and_explicit_endpoints',async()=>{
 const C=await import(file('static/twin/editor/gutter_controls.js'));
 for(const [f,want] of [[0,0],[1,1],[.000001,.0001],[.000049,.0001],[.999951,.9999],[.999999,.9999],[.123456,.1235]]){
  assert.equal(C.roundAt(f),want);
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[{at:.5}];edge(0);
  const input=control('Downspout 1 fraction');input.value=String(f);fire(input,'change');await tick();await cards.queue(()=>{});await tick();
  assert.deepEqual(ops[0].downspouts,[{at:want}],'numeric edit preserves interior/end distinction');
  assert.deepEqual(C.snapOrExact(plan,'b','r',0,f,[]),{at:want},'drag storage uses same rounding');
 }
});

await test('test_convert_both_ways_numeric_edit_and_reset',async()=>{
  // Number row: "Keep exactly here" turns authored 0.2 (snapped to corner 0) into {at: 0}.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.2,{at:.55}];edge(0);
  const rows=host.querySelectorAll('[data-downspout-row]');assert.equal(rows.length,2);
  assert.equal(rows[0].dataset.downspoutKind,'corner');
  assert.ok(!rows[0].textContent.includes('Placed by hand'));
  assert.equal(rows[1].dataset.downspoutKind,'exact');
  assert.ok(rows[1].textContent.includes('Placed by hand'));
  const keepBtn=rows[0].querySelectorAll('button').find(b=>b.textContent==='Keep exactly here');
  const snapBtn=rows[1].querySelectorAll('button').find(b=>b.textContent==='Snap to a corner');
  assert.ok(keepBtn,'number row has Keep exactly here');
  assert.ok(snapBtn,'exact row has Snap to a corner');
  click(keepBtn);await tick();await cards.queue(()=>{});await tick();
  assert.equal(ops.length,1,'convert to exact is one operation');
  assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[{at:0},{at:.55}]});
  // Exact row: "Snap to a corner" picks nearest UNOCCUPIED candidate (corner 1, since 0.2 occupies corner 0).
  ops.length=0;click(snapBtn);await tick();await cards.queue(()=>{});await tick();
  assert.equal(ops.length,1,'convert to corner is one operation');
  assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[.2,1]});
  // Row buttons include row number in aria-label and last row carries bottom divider marker.
  assert.equal(keepBtn.getAttribute('aria-label'),'Keep exactly here for downspout 1');
  assert.equal(snapBtn.getAttribute('aria-label'),'Snap to a corner for downspout 2');
  assert.equal(rows[0].querySelectorAll('button')[1].getAttribute('aria-label'),'Remove downspout 1');
  assert.equal(rows[1].dataset.downspoutLast,'');
  assert.equal(rows[0].dataset.downspoutLast,undefined);
  // With NO unoccupied corner free, "Snap to a corner" is disabled with exact title.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,1,{at:.55}];edge(0);
  const fullRows=host.querySelectorAll('[data-downspout-row]');
  const disabledSnap=fullRows[2].querySelectorAll('button').find(b=>b.textContent==='Snap to a corner');
  assert.equal(disabledSnap.disabled,true,'Snap to a corner disabled when no free corner');
  assert.equal(disabledSnap.title,'No free corner on this edge.');
  // Ruling (Item 5): "Keep exactly here" on a merged same-edge number ([0.8, 0.9]) is disabled on row 2 with exact title, enabled on row 1.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.8,.9];edge(0);
  const mergedRows=host.querySelectorAll('[data-downspout-row]');
  const winnerKeep=mergedRows[0].querySelectorAll('button').find(b=>b.textContent==='Keep exactly here');
  const loserKeep=mergedRows[1].querySelectorAll('button').find(b=>b.textContent==='Keep exactly here');
  assert.equal(winnerKeep.disabled,false,'winning spout keeps Keep exactly here enabled');
  assert.equal(loserKeep.disabled,true,'merged row disables Keep exactly here');
  assert.equal(loserKeep.title,'This downspout shares an outlet with another one.');
  // N4: [0] -> Keep exactly here -> [{at:0}] -> Snap to a corner -> [0]; same for [0,1].
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0];edge(0);
  click(host.querySelectorAll('[data-downspout-row]')[0].querySelectorAll('button').find(b=>b.textContent==='Keep exactly here'));
  await tick();await cards.queue(()=>{});await tick();
  assert.deepEqual(ops[0].downspouts,[{at:0}]);
  plan=structuredClone(plan);roof().edges[0].downspouts=[{at:0}];ops.length=0;edge(0);
  const snapBack=host.querySelectorAll('[data-downspout-row]')[0].querySelectorAll('button').find(b=>b.textContent==='Snap to a corner');
  assert.equal(snapBack.disabled,false,'Snap to a corner enabled for [{at:0}]');
  click(snapBack);await tick();await cards.queue(()=>{});await tick();
  assert.deepEqual(ops[0].downspouts,[0],'[0] -> Keep -> Snap returns [0]');
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[{at:0},1];edge(0);
  const snapBack2=host.querySelectorAll('[data-downspout-row]')[0].querySelectorAll('button').find(b=>b.textContent==='Snap to a corner');
  assert.equal(snapBack2.disabled,false,'Snap to a corner enabled for [{at:0},1]');
  click(snapBack2);await tick();await cards.queue(()=>{});await tick();
  assert.deepEqual(ops[0].downspouts,[0,1],'[{at:0},1] -> Snap returns [0,1]');
  // Numeric edit on an {at} row keeps it {at} and rounds to 1e-4.
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.2,{at:.55}];edge(0);
  ops.length=0;const exactInput=control('Downspout 2 fraction');
  exactInput.value='0.623456';fire(exactInput,'change');await tick();await cards.queue(()=>{});await tick();
  assert.equal(ops.length,1,'numeric edit is one operation');
  assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[.2,{at:.6235}]});
  // Numeric edit on a number row keeps it a number.
  ops.length=0;const numInput=control('Downspout 1 fraction');
  numInput.value='0.85';fire(numInput,'change');await tick();await cards.queue(()=>{});await tick();
  assert.equal(ops.length,1);
  assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[.85,{at:.55}]});
  // Reset clears both numbers and {at} entries with downspouts: null.
  ops.length=0;await press('Reset to automatic');
  assert.deepEqual(ops,[{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:null}]);
});
await test('test_two_quick_edits_preserve_both_and_guard_stale_index',async()=>{
  plan=structuredClone(original);roof().edges[0].gutter=true;roof().edges[0].downspouts=[.2,{at:.55}];
  ops=[];enabled=true;
  let releaseFirst;
  const firstInFlight=new Promise(resolve=>{releaseFirst=resolve;});
  cards=createCards({getPlan:()=>plan,getLabel:()=>'Roof',getKit:()=>({}),canEdit:()=>enabled,edit:()=>{},
    op:async operation=>{
      ops.push(operation);
      if(ops.length===1)await firstInFlight;
      plan=structuredClone(plan);
      if('downspouts' in operation)roof().edges[operation.edge].downspouts=operation.downspouts;
    },select(){},ask(){}});
  edge(0);
  const input1=control('Downspout 1 fraction');
  const snapBtn2=host.querySelectorAll('[data-downspout-row]')[1].querySelectorAll('button').find(b=>b.textContent==='Snap to a corner');
  // Edit input 1, then immediately click Snap on row 2 while op 1 is still in flight.
  input1.value='0.15';input1.dispatchEvent({type:'change',bubbles:true});
  snapBtn2.dispatchEvent({type:'click',bubbles:true});
  releaseFirst();
  await cards.queue(()=>{});await tick();
  assert.equal(ops.length,2,'both edits sent');
  assert.deepEqual(ops[1].downspouts,[.15,1],'second queued edit sees first edit on then-current plan');
  // Stale numeric edit when list shrank is ignored.
  ops.length=0;plan=structuredClone(plan);roof().edges[0].downspouts=[.15];
  const staleInput=control('Downspout 2 fraction');
  if(staleInput){staleInput.value='0.33';fire(staleInput,'change');await cards.queue(()=>{});await tick();}
  assert.equal(ops.length,0,'stale index edit ignored');
  // N1: Remove 1 then Remove 2 before first save returns on [0,{at:.3},{at:.6}] keeps [{at:.6}].
  plan=structuredClone(original);roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,{at:.3},{at:.6}];
  ops=[];let releaseRemove;
  const removeInFlight=new Promise(resolve=>{releaseRemove=resolve;});
  cards=createCards({getPlan:()=>plan,getLabel:()=>'Roof',getKit:()=>({}),canEdit:()=>enabled,edit:()=>{},
    op:async operation=>{
      ops.push(operation);
      if(ops.length===1)await removeInFlight;
      plan=structuredClone(plan);
      if('downspouts' in operation)roof().edges[operation.edge].downspouts=operation.downspouts;
    },select(){},ask(){}});
  edge(0);
  const rm1=host.querySelector('[aria-label="Remove downspout 1"]');
  const rm2=host.querySelector('[aria-label="Remove downspout 2"]');
  rm1.dispatchEvent({type:'click',bubbles:true});
  rm2.dispatchEvent({type:'click',bubbles:true});
  await Promise.resolve();await Promise.resolve();
  assert.equal(ops.length,1,'first remove is in flight');
  releaseRemove();
  await cards.queue(()=>{});await tick();
  assert.equal(ops.length,2);
  assert.deepEqual(ops[1].downspouts,[{at:.6}],'Remove 1 then Remove 2 keeps {at:.6}');
  // N1: Remove 1 then Edit 2 before first save returns on [0,{at:.3},{at:.6}] gives [{at:.45},{at:.6}].
  plan=structuredClone(original);roof().edges[0].gutter=true;roof().edges[0].downspouts=[0,{at:.3},{at:.6}];
  ops=[];let releaseRmEdit;
  const rmEditInFlight=new Promise(resolve=>{releaseRmEdit=resolve;});
  cards=createCards({getPlan:()=>plan,getLabel:()=>'Roof',getKit:()=>({}),canEdit:()=>enabled,edit:()=>{},
    op:async operation=>{
      ops.push(operation);
      if(ops.length===1)await rmEditInFlight;
      plan=structuredClone(plan);
      if('downspouts' in operation)roof().edges[operation.edge].downspouts=operation.downspouts;
    },select(){},ask(){}});
  edge(0);
  const rmFirst=host.querySelector('[aria-label="Remove downspout 1"]');
  const inputSecond=control('Downspout 2 fraction');
  rmFirst.dispatchEvent({type:'click',bubbles:true});
  inputSecond.value='0.45';inputSecond.dispatchEvent({type:'change',bubbles:true});
  await Promise.resolve();await Promise.resolve();
  assert.equal(ops.length,1,'first remove is in flight before edit completes');
  releaseRmEdit();
  await cards.queue(()=>{});await tick();
  assert.equal(ops.length,2);
  assert.deepEqual(ops[1].downspouts,[{at:.45},{at:.6}],'Remove 1 then Edit 2 updates {at:.3} to {at:.45}');
});
await test('test_add_split_edge_longest_piece_and_placed_clearance',async()=>{
  const {addDownspout}=await import(file('static/twin/editor/gutter_controls.js'));
  setup();roof().edges[0].gutter=true;
  const a=roof().area[0], b=roof().area[1], FT=.3048;
  const world=f=>[(a[0]+f*(b[0]-a[0]))*FT,roof().plate*FT,-(a[1]+f*(b[1]-a[1]))*FT];
  // 40 ft edge split into 32 ft piece [0, 0.8] and 1.2 ft sliver [0.9, 0.93], entries [0, {at: 0.4}, 1].
  roof().edges[0].downspouts=[0,{at:.4},1];
  const splitSnap={
    runs:[
      {id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:world(0),b:world(.8)}]},
      {id:'b:r:0~2',building:'b',segments:[{roof:'r',edge:0,a:world(.9),b:world(.93)}]},
    ],
    spouts:[
      {id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:0},source:'override',authoredFraction:0,authoredIndex:0,flags:[]},
      {id:'b:r:0:1',run:'b:r:0',edge:{roof:'r',edge:0,fraction:.4},source:'override',authoredFraction:.4,authoredIndex:1,exact:true,flags:[]},
      {id:'b:r:0~2:0',run:'b:r:0~2',edge:{roof:'r',edge:0,fraction:1},source:'override',authoredFraction:1,authoredIndex:2,flags:[]},
    ],
  };
  const next=addDownspout(plan,'b','r',0,splitSnap,[]);
  assert.ok(next,'adds inside the 32 ft piece');
  const added=next.at(-1);
  assert.ok(added&&typeof added==='object'&&added.at>0.42&&added.at<0.8,
    `must pick longest clear span inside 32 ft piece (~0.6125), not 1.2 ft sliver (0.915): ${JSON.stringify(added)}`);
  assert.equal(added.at,Math.round(added.at*1e4)/1e4,'rounded to 1e-4');
  // Add's 1 ft clearance uses placed fractions, not authored ones:
  // authored 0.49 snapped to corner 0 must NOT block midpoint 0.5!
  roof().edges[0].downspouts=[.49,1];
  const placedSnap={
    runs:[{id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:world(0),b:world(1)}]}],
    spouts:[
      {id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:0},source:'override',authoredFraction:.49,authoredIndex:0,flags:[]},
      {id:'b:r:0:1',run:'b:r:0',edge:{roof:'r',edge:0,fraction:1},source:'override',authoredFraction:1,authoredIndex:1,flags:[]},
    ],
  };
  const nextPlaced=addDownspout(plan,'b','r',0,placedSnap,[]);
  assert.deepEqual(nextPlaced.at(-1),{at:.5},'authored 0.49 placed at 0 does not block midpoint 0.5');
});
await test('test_reset_clears_override',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[];edge(0);await press('Reset to automatic');
  assert.deepEqual(ops,[{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:null}]);
});
await test('test_new_part3_check_texts',async()=>{
  const {gutterCheckItems,gutterAcknowledgement}=await import(file('static/twin/editor/gutter_controls.js'));
  setup();
  const run={id:'b:r:0',building:'b',segments:[{roof:'r',edge:0}]};
  for(const [flag,expected] of [
    ['placed-off-corner','This downspout was placed by hand away from an outside corner.'],
    ['over-opening','This downspout passes a door or window.'],
    ['no-support','This downspout has no wall or post to fasten to.'],
  ]){
    const spout={id:`b:r:0:${flag}`,run:run.id,edge:{roof:'r',edge:0,fraction:.5},top:[0,3,0],
      source:'override',authoredFraction:.5,authoredIndex:0,exact:true,flags:[flag]};
    const [item]=gutterCheckItems(plan,{runs:[run],spouts:[spout]});
    assert.ok(item,flag);assert.equal(item.reason,expected);
    const ack=gutterAcknowledgement(plan,item);
    assert.deepEqual(ack,{op:'set_roof_edge',building:'b',roof:'r',edge:0,gutter_ack:[flag]});
  }
});
await test('test_check_list_lists_each_flag_with_reason',async()=>{
  const {gutterCheckItems}=await import(file('static/twin/editor/gutter_controls.js'));
  const {createChecks}=await import(file('static/twin/editor/checks.js'));
  setup();const flags=['no-outside-corner','hang','stub','inner-end','clipped-end','no-safe-landing','no-outlet','outlet-blocked','merged-override'];
  const run={id:'b:r:0',building:'b',segments:[{roof:'r',edge:0}],flags:['no-outside-corner']};
  const spout={id:'b:r:0:0',run:run.id,edge:{roof:'r',edge:0,fraction:.1},top:[0,3,0],flags,
    merged:[{run:'b:other:2',fraction:.75},{run:'b:other:3',fraction:.25}]};
  const items=gutterCheckItems(plan,{runs:[run],spouts:[spout]});
  assert.equal(items.length,1,'one physical downspout, one row');
  for(const flag of flags)assert.ok(items[0].flags.includes(flag),flag);
  assert.match(items[0].reason,/no downspout location.*building.*short stub/i);
  assert.ok(!/b:r:|b:other:|0\.75|0\.25/.test(items[0].label+' '+items[0].reason));
  assert.match(items[0].reason,/merged/i);assert.equal(items[0].roof,'r');
  // Real Check queue consumes builder output and opens the selected roof/downspout.
  roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];
  const selected=[],focused=[],abort=new AbortController();
  const checks=createChecks({},{api:{op:async()=>{},report:e=>{throw e;}},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,
    tools:{select:r=>selected.push(r),focusDownspout:r=>focused.push(r)},panel:{checks(){}},canEdit:()=>true,signal:abort.signal,
    flags:{dismiss(){},review(){}},dock:{properties:{clear(){},render(){}}}});
  checks.show();const entry=checks.queue().find(i=>i.kind==='gutter');assert.ok(entry,'Check queue contains gutter issues');checks.show(entry);
  const row=document.getElementById('check-card').querySelector('[data-gutter-check]');assert.ok(row,'clickable list of gutter checks');
  click(row);await tick();assert.ok(selected.some(r=>r.id==='r'||r.pieceId==='r'));assert.ok(focused.length);
  abort.abort();
});
await test('test_bulk_actions_disable_noop_batches',async()=>{
  setup();roofCard();assert.equal(button('Remove all gutters').disabled,true);
  setup();roof().edges.forEach(e=>e.gutter=true);roofCard();assert.equal(button('Gutters on all eaves').disabled,true);
  setup();roof().edges[0].gutter=true;roofCard();await press('Gutters on all eaves');assert.deepEqual(ops[0].ops.map(o=>o.edge),[1,2,3]);
});
await test('test_merged_locations_use_the_authored_edge_or_porch',async()=>{
  const {gutterCheckItems}=await import(file('static/twin/editor/gutter_controls.js'));
  setup();roof().name='Main roof';plan.buildings[0].porches=[{id:'p',name:'Garden porch'}];
  const runs=[{id:'winner',building:'b',segments:[{roof:'r',edge:0}]},
    {id:'wrapped',building:'b',segments:[{roof:'r',edge:0},{roof:'r',edge:2}]}];
  const spout={id:'s',run:'winner',edge:{roof:'r',edge:0,fraction:0},flags:['merged-override'],
    merged:[{run:'wrapped',roof:'r',edge:2,porch:null,fraction:.3},
      {run:'wrapped',roof:null,edge:0,porch:'p',fraction:0}]};
  const [item]=gutterCheckItems(plan,{runs,spouts:[spout]});
  assert.match(item.reason,/Merged locations: Main roof, back edge, 12 ft from the start; Garden porch, at the start\./);
});
await test('test_gutter_check_reason_once_and_header_clear_of_close',async()=>{
  const {createChecks}=await import(file('static/twin/editor/checks.js'));
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[.5];plan.buildings[0].levels[0].outline=[];
  const abort=new AbortController();
  const checks=createChecks({},{api:{op:async()=>{}},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,
    tools:{select(){},focusDownspout(){}},panel:{checks(){}},canEdit:()=>true,signal:abort.signal,
    flags:{dismiss(){},review(){}}});
  try{
    checks.show();const issues=checks.queue().filter(i=>i.kind==='gutter');assert.equal(issues.length,1);
    const issue=issues[0];checks.show(issue);
    const card=document.getElementById('check-card');
    assert.equal(card.textContent.split(issue.reason).length-1,1,'reason appears only in its issue row');
    const header=card.querySelector('header');assert.ok(header,'title and Close share a flow header');
    assert.equal(header.querySelector('h3').textContent,'Check this piece');
    assert.ok(header.querySelector('[aria-label="Close check"]'),'Close reserves its own space in the header');
    assert.equal(card.querySelector('p'),null,'no duplicate headline paragraph');
  }finally{abort.abort();}
});
await test('test_edge_typing_survives_plan_swap',async()=>{
  setup();edge(0);const pitch=control('Pitch');pitch.focus();pitch.value='12.3';
  plan=structuredClone(plan);plan.buildings[0].name='Renamed';cards.draw();
  assert.equal(control('Pitch'),pitch);assert.equal(pitch.value,'12.3');
});
await test('test_one_shared_content_cache_for_preview_and_confirmed',async()=>{
  const g=await import(file('static/twin/gutters.js')), {buildTwin}=await import(file('static/twin/twin_generator.js'));
  const {disposeObject}=await import(file('static/twin/twin_library.js'));
  const {gutterSnapshot}=await import(file('static/twin/editor/gutter_controls.js'));
  setup();roof().edges[0].gutter=true;g._gutterPlacementStats.clearCache();
  const preview=structuredClone(plan),twin=buildTwin(preview,{manifest:{},materials:{}},'low');await twin.ready;
  const confirmed=structuredClone(plan);assert.equal(gutterSnapshot(confirmed),g.gutterPlacement(preview));
  assert.equal(g._gutterPlacementStats.calls,1);console.log('PLACEMENT_PREVIEW_CONFIRMED_PASSES',g._gutterPlacementStats.calls);disposeObject(twin.root);
});
await test('test_roof_edge_20_moves_make_zero_extra_placement_passes',async()=>{
  const g=await import(file('static/twin/gutters.js'));
  setup();roof().edges[0].gutter=true;g._gutterPlacementStats.clearCache();
  const rig=handleRig();try{
    const h=rig.handles.handles().find(h=>h.kind==='roof_edge');assert.ok(h);const before=g._gutterPlacementStats.calls;
    assert.ok(rig.handles.begin(rig.event(h.at)));
    for(let i=1;i<=20;i++)rig.handles.update(rig.event([h.at[0],h.at[1]-i/10,h.at[2]]));
    assert.equal(g._gutterPlacementStats.calls-before,0);console.log('PLACEMENT_EXTRA_PASSES_20_MOVES',g._gutterPlacementStats.calls-before);
    await rig.handles.finish(true);
  }finally{rig.abort.abort();}
});
await test('test_shared_cache_is_bounded_and_empty_placement_is_shared',async()=>{
  const g=await import(file('static/twin/gutters.js'));
  setup();g._gutterPlacementStats.clearCache();assert.equal(g.gutterPlacement(plan),g.gutterPlacement(structuredClone(plan)));
  assert.equal(g._gutterPlacementStats.calls,0);
  roof().edges[0].gutter=true;const first=structuredClone(plan);g.gutterPlacement(first);
  for(let i=1;i<=16;i++){const p=structuredClone(plan);p.buildings[0].position=[i*100,0];g.gutterPlacement(p);}
  assert.equal(g._gutterPlacementStats.calls,17);g.gutterPlacement(first);assert.equal(g._gutterPlacementStats.calls,18,'old object front-cache cannot retain evicted placement');
});
await test('test_gutter_acknowledgement_is_not_bake_geometry',async()=>{
  const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
  setup();plan.buildings[0].porches=[{id:'p',gutter:true}];
  const before=authoredGeometry(plan),next=structuredClone(plan);next.buildings[0].porches[0].gutter_ack=['hang'];
  assert.equal(authoredGeometry(next),before,'acknowledging a note must not dirty lighting');
});
await test('test_closed_check_never_computes_and_acknowledgement_leaves_count',async()=>{
  const g=await import(file('static/twin/gutters.js')), {createChecks}=await import(file('static/twin/editor/checks.js'));
  setup();roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];g._gutterPlacementStats.clearCache();
  const abort=new AbortController(),counts=[];
  const checks=createChecks({},{api:{op:async o=>{
    ops.push(o);plan=structuredClone(plan);const e=roof().edges[o.edge];e.gutter_ack=o.gutter_ack;
  }},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,tools:{select(){},focusDownspout(){}},panel:{checks:n=>counts.push(n)},canEdit:()=>true,signal:abort.signal,
    flags:{dismiss(){},review(){}},dock:{properties:{clear(){},render(){}}}});
  await tick();assert.equal(g._gutterPlacementStats.calls,0);console.log('PLACEMENT_CLOSED_CHECK_PASSES',g._gutterPlacementStats.calls);
  checks.show();assert.equal(g._gutterPlacementStats.calls,1);const issue=checks.queue().find(i=>i.kind==='gutter');assert.ok(issue);
  const ok=document.getElementById('check-card').querySelectorAll('button').find(n=>n.textContent==='Looks fine');assert.ok(ok);
  click(ok);await tick();assert.equal(ops[0].op,'set_roof_edge');assert.ok(ops[0].gutter_ack.includes('hang'));
  assert.equal(checks.queue().filter(i=>i.kind==='gutter').length,0);assert.equal(counts.at(-1),0);assert.equal(g._gutterPlacementStats.calls,1,'ack metadata reuses placement');
  checks.dismiss(false);plan=structuredClone(plan);roof().overhang=.5;await tick();
  assert.equal(g._gutterPlacementStats.calls,1,'closed Check does not place even after geometry changes');
  abort.abort();
});
await test('test_closed_check_counts_renderer_cached_issues_without_placing',async()=>{
  const g=await import(file('static/twin/gutters.js')), {createChecks}=await import(file('static/twin/editor/checks.js'));
  setup();roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];g._gutterPlacementStats.clearCache();
  const abort=new AbortController(),counts=[];
  const checks=createChecks({},{api:{op:async()=>{}},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,
    tools:{select(){}},panel:{checks:n=>counts.push(n)},canEdit:()=>true,signal:abort.signal,flags:{dismiss(){},review(){}}});
  assert.equal(g._gutterPlacementStats.calls,0);
  g.gutterPlacement(structuredClone(plan)); // The renderer publishes an equal-content plan.
  checks.sync();assert.ok(counts.at(-1)>0,'closed counter consumes the renderer result');
  assert.equal(g._gutterPlacementStats.calls,1,'Check never adds a placement pass');
  plan=structuredClone(plan);roof().edges[0].gutter_ack=['no-outside-corner','hang','stub','inner-end','clipped-end','no-safe-landing','no-outlet','outlet-blocked','merged-override'];
  checks.sync();assert.equal(counts.at(-1),0);assert.equal(g._gutterPlacementStats.calls,1);
  abort.abort();
});
await test('test_porch_and_awning_toggle',async()=>{
  const {sceneRows}=await import(file('static/twin/editor/scene_tree.js'));
  for(const kind of ['porch','awning']){
    setup();const b=plan.buildings[0],p={id:kind,kind,level:'L1',polygon:[[0,0],[8,0],[8,4],[0,4]],floor:0,roof:{kind:'shed',height:8}};
    if(kind==='porch'){
      b.porches=[p];assert.ok(sceneRows(plan).some(r=>r.id===kind),'porch is reachable in Scene');
      cards.draw({pieceId:kind,buildingId:'b'});await toggle();
      assert.deepEqual(ops,[{op:'set',building:'b',id:kind,field:'gutter',value:true}]);
    }else{
      plan=structuredClone(input.awningPlan);
      const shade=plan.buildings[0].roofs.find(r=>r.id==='aw');shade.edges[0].gutter=false;
      assert.ok(sceneRows(plan).some(r=>r.id==='aw'&&r.kind==='roof'),'migrated awning is reachable as a roof in Scene');
      cards.showRoofEdge({id:'aw',building:'b',edge:0});await toggle();
      assert.deepEqual(ops,[{op:'set_roof_edge',building:'b',roof:'aw',edge:0,gutter:true}]);
    }
  }
});
await test('test_awning_scene_row_has_effective_roof_eye',async()=>{
  setup();const {createSceneTree}=await import(file('static/twin/editor/scene_tree.js'));
  plan=structuredClone(input.awningPlan);const hidden=[];
  const treeHost=document.createElement('div');document.body.append(treeHost);
  const tree=createSceneTree({host:treeHost,getPlan:()=>plan,getSelection:()=>null,select(){},floors:{current:()=> 'b:L1',hidden:()=>false},
    visibility:{isHidden:()=>false,isLocked:()=>false,hide:id=>hidden.push(id),subscribe:()=>()=>{}}});
  const row=treeHost.querySelector('[data-scene-id="aw"]');assert.ok(row);
  const eye=row.querySelector('[data-row-eye]');assert.ok(eye);click(eye);assert.deepEqual(hidden,['aw']);
  assert.ok(row.querySelector('[data-scene-select]'));tree.dispose();treeHost.remove();
});
await test('test_server_and_ui_eaves_match',async()=>{
  const {eaveEdgeIndices}=await import(file('static/twin/gutters.js'));
  for(const sample of input.eaves)assert.deepEqual(eaveEdgeIndices(sample.building,sample.building.roofs[0]),sample.expected);
});
await test('test_scene_focus_and_context_remove',async()=>{
  setup();roof().edges[0].gutter=true;
  const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
  const {mountTwin}=await import(file('static/twin/twin_view.js'));
  // Exercise the real scene arbiter: Check focus and the canvas contextmenu.
  globalThis.fetch=async()=>({ok:true,status:200,text:async()=>'{}',json:async()=>({revision:1,entries:{}})});
  const sceneHost=document.createElement('div');sceneHost.className='editor-shell';document.body.append(sceneHost);
  const view=await mountTwin(sceneHost,{plan,kit:{manifest:{},materials:{}},tier:'low',bake:false,preserveCamera:true});
  const abort=new AbortController();
  try{
    const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>({}),getSheets:()=>({}),
      canEdit:()=>enabled,op:async o=>ops.push(o),edit:assert.fail,panel:{clearSelection(){},focusSelection(){}},signal:abort.signal});
    const s=spouts()[0];assert.ok(s);
    tools.chooseFloor('b:L1');
    tools.select({id:'r',building:'b'});
    tools.focusDownspout({roof:'r',building:'b',edge:s.edge.edge,top:s.top,spout:s.id});
    while(!view.ready)await new Promise(resolve=>setTimeout(resolve,1));
    assert.equal(view.state.view,'ext','Check exposes the roof above a cutaway');
    assert.ok(view.controls.target.distanceTo(new THREE.Vector3(...s.top))<1e-6);
    const h=tools.handles().find(h=>h.kind==='downspout');assert.ok(h);
    view.camera.updateMatrixWorld(true);const p=new THREE.Vector3(...s.top).project(view.camera);
    fire(view.renderer3.domElement,'contextmenu',{clientX:(p.x+1)*720,clientY:(1-p.y)*450});
    await tick();assert.equal(ops.length,1);assert.equal(ops[0].op,'set_roof_edge');assert.equal(ops[0].downspouts.length,spouts().length-1);
  }finally{abort.abort();view.dispose?.();sceneHost.remove();}
});
finish();
"""


STUB_DRIVER = PRELUDE.replace(
    "return next(spec, ctx);",
    "if (spec === '../gutters.js' && ctx.parentURL?.includes('/editor/')) return {url: data(`\n"
    "export const eaveEdgeIndices = (b, r) => r.edges.flatMap((e, i) => e.setting === 'sloped' ? [i] : []);\n"
    "export const gutterPlacement = plan => globalThis.__stubPlacement(plan);\n"
    "export const cachedGutterPlacement = plan => globalThis.__stubPlacement(plan);\n"
    "export const gutterCandidates = plan => globalThis.__stubCandidates(plan);\n"
    "`), shortCircuit: true};\n"
    "return next(spec, ctx);",
) + r"""
const THREE=await import(three);
const FT=.3048;
let stubSnapshot={runs:[],spouts:[]}, stubCands=[];
globalThis.__stubPlacement=()=>stubSnapshot;
globalThis.__stubCandidates=()=>stubCands;
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createChecks}=await import(file('static/twin/editor/checks.js'));
const plan=structuredClone(input.plan);
const roof=plan.buildings[0].roofs[0];
roof.edges[0].gutter=true;
roof.edges[0].downspouts=[.6,{at:.6}];
const ops=[];
const a=roof.area[0], b=roof.area[1];
const toWorld=p=>[p[0]*FT,p[2]*FT,-p[1]*FT];
stubSnapshot={
  runs:[{id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:toWorld([...a,roof.plate]),b:toWorld([...b,roof.plate])}]}],
  spouts:[
    {id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:0},top:toWorld([a[0],a[1],roof.plate]),
      source:'override',authoredFraction:.6,authoredIndex:0,flags:[]},
    {id:'b:r:0:1',run:'b:r:0',edge:{roof:'r',edge:0,fraction:.6},top:toWorld([a[0]+.6*(b[0]-a[0]),a[1]+.6*(b[1]-a[1]),roof.plate]),
      source:'override',authoredFraction:.6,authoredIndex:1,exact:true,flags:['placed-off-corner','over-opening','no-support']},
  ],
};
stubCands=[{building:'b',roof:'r',edge:0,fraction:0,occupied:true},{building:'b',roof:'r',edge:0,fraction:1,occupied:false}];

await test('test_remove_and_drag_by_authoredIndex',async()=>{
  const canvas=document.createElement('canvas');document.body.append(canvas);
  const camera=new THREE.PerspectiveCamera(45,1440/900,.01,1000);
  camera.position.set(20*FT,110*FT,-14.99*FT);camera.lookAt(20*FT,10*FT,-15*FT);camera.updateMatrixWorld(true);
  const view={renderer3:{domElement:canvas},camera,controls:new THREE.EventDispatcher(),groups:{levels:{}},pick:()=>null};
  const abort=new AbortController();
  const handles=createHandles({view,getPlan:()=>plan,getSelection:()=>({kind:'roof',id:'r',building:'b'}),
    canEdit:()=>true,drag:{},onCommit:async op=>ops.push(op),signal:abort.signal});
  const ev=p=>{const v=new THREE.Vector3(...toWorld(p)).project(camera);return {clientX:(v.x+1)*720,clientY:(1-v.y)*450};};
  try{
    const list=handles.handles().filter(h=>h.kind==='downspout');
    assert.equal(list.length,2);
    const second=list.find(h=>h.spout==='b:r:0:1');
    assert.equal(second.authoredIndex,1);
    // Remove by authoredIndex: both entries have fraction 0.6, must remove index 1 ({at:0.6}) and keep index 0 (0.6).
    assert.equal(await handles.removeAt(ev(second.at)),true);
    assert.equal(ops.length,1);
    assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[.6]});
    // Drag entry at authoredIndex 1 leaves index 0 untouched.
    ops.length=0;
    assert.ok(handles.begin(ev(second.at)));
    handles.update(ev([a[0]+.75*(b[0]-a[0]),a[1]+.75*(b[1]-a[1]),second.at[2]]));
    await handles.finish();
    assert.equal(ops.length,1);
    assert.equal(ops[0].downspouts[0],.6);
    assert.ok(ops[0].downspouts[1]&&Math.abs(ops[0].downspouts[1].at-.75)<.005,JSON.stringify(ops[0].downspouts));
  }finally{abort.abort();}
});
await test('test_stub_cards_keep_exactly_here_uses_authoredIndex_placed_fraction',async()=>{
  ops.length=0;
  const cards=createCards({getPlan:()=>plan,getLabel:()=>'Roof',getKit:()=>({}),
    canEdit:()=>true,edit:()=>{},op:async o=>ops.push(o),select(){},ask(){}});
  cards.showRoofEdge({id:'r',building:'b',edge:0});
  const rows=document.getElementById('piece-card').querySelectorAll('[data-downspout-row]');
  assert.equal(rows.length,2);
  const keep=rows[0].querySelectorAll('button').find(b=>b.textContent==='Keep exactly here');
  click(keep);await tick();await cards.queue(()=>{});await tick();
  assert.equal(ops.length,1);
  // Entry 0 had authored 0.6 snapped to placed fraction 0; Keep exactly here writes {at: 0}.
  assert.deepEqual(ops[0],{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:[{at:0},{at:.6}]});
});
await test('test_stub_keep_exactly_here_merged_cross_run',async()=>{
  const {placedFraction}=await import(file('static/twin/editor/gutter_controls.js'));
  const crossPlan=structuredClone(plan);
  crossPlan.buildings[0].roofs[0].edges[0].downspouts=[.9];
  const prevSnap=stubSnapshot;
  stubSnapshot={
    runs:[
      {id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:toWorld([...a,roof.plate]),b:toWorld([...b,roof.plate])}]},
      {id:'b:r:1',building:'b',segments:[{roof:'r',edge:1,a:toWorld([...b,roof.plate]),b:toWorld([...roof.area[2],roof.plate])}]},
    ],
    spouts:[
      {id:'b:r:1:0',run:'b:r:1',edge:{roof:'r',edge:1,fraction:0},top:toWorld([b[0],b[1],roof.plate]),
        source:'override',authoredFraction:.05,authoredIndex:0,flags:['merged-override'],
        merged:[{run:'b:r:0',roof:'r',edge:0,porch:null,fraction:.9}]},
    ],
  };
  try{
    assert.ok(Math.abs(placedFraction(crossPlan,'b','r',0,0,.9)-1)<1e-6,'uses fraction of spout it merged into');
    // Ruling (Item 5): Keep exactly here is disabled on cross-run merged row with exact title.
    const mergedCards=createCards({getPlan:()=>crossPlan,getLabel:()=>'Roof',getKit:()=>({}),
      canEdit:()=>true,edit:()=>{},op:async o=>ops.push(o),select(){},ask(){}});
    mergedCards.showRoofEdge({id:'r',building:'b',edge:0});
    const keepBtn=document.getElementById('piece-card').querySelector('[aria-label="Keep exactly here for downspout 1"]');
    assert.equal(keepBtn.disabled,true,'cross-run merged row disables Keep exactly here');
    assert.equal(keepBtn.title,'This downspout shares an outlet with another one.');
  }finally{stubSnapshot=prevSnap;}
});
await test('test_stub_nearExact_contract_and_off_centre_exact_grab_and_rounded_noop',async()=>{
  const {nearestFreeCandidate,placedFraction}=await import(file('static/twin/editor/gutter_controls.js'));
  const prevSnap=stubSnapshot, prevCands=stubCands;
  // N4 with nearExact: [{at:0}, 1] where corner 0 has nearExact for index 0 (self) and corner 1 is occupied.
  const n4Plan=structuredClone(plan);
  n4Plan.buildings[0].roofs[0].edges[0].downspouts=[{at:0},1];
  stubSnapshot={
    runs:[{id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:toWorld([-2,0,roof.plate]),b:toWorld([42,0,roof.plate])}]}],
    spouts:[
      {id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:0},top:toWorld([-2,-2.25,roof.plate]),
        source:'override',authoredFraction:0,authoredIndex:0,exact:true,flags:[]},
      {id:'b:r:0:1',run:'b:r:0',edge:{roof:'r',edge:0,fraction:1},top:toWorld([42,-2.25,roof.plate]),
        source:'override',authoredFraction:1,authoredIndex:1,flags:[]},
    ],
  };
  stubCands=[
    {building:'b',roof:'r',edge:0,fraction:0,occupied:false,nearExact:[{roof:'r',edge:0,index:0}]},
    {building:'b',roof:'r',edge:0,fraction:1,occupied:true,nearExact:[]},
  ];
  try{
    // Converting index 0 ignores its own nearExact entry -> snaps back to corner 0.
    assert.equal(nearestFreeCandidate(n4Plan,'b','r',0,0,0),0,'self nearExact does not block Snap to a corner');
    // Another entry's nearExact blocks corner 0!
    stubCands[0].nearExact=[{roof:'r',edge:0,index:1}];
    assert.equal(nearestFreeCandidate(n4Plan,'b','r',0,0,0),null,'other nearExact blocks corner 0');
    // N2: 4 px move on {at:0} at overhang 2 keeps preview at x=-2 and commits nothing.
    stubCands[0].nearExact=[{roof:'r',edge:0,index:0}];
    const canvas=document.createElement('canvas');document.body.append(canvas);
    const camera=new THREE.PerspectiveCamera(45,1440/900,.01,1000);
    camera.position.set(20*FT,110*FT,-14.99*FT);camera.lookAt(20*FT,10*FT,-15*FT);camera.updateMatrixWorld(true);
    const view={renderer3:{domElement:canvas},camera,controls:new THREE.EventDispatcher(),groups:{levels:{}},pick:()=>null};
    const abort=new AbortController();ops.length=0;
    const handles=createHandles({view,getPlan:()=>n4Plan,getSelection:()=>({kind:'roof',id:'r',building:'b'}),
      canEdit:()=>true,drag:{},onCommit:async op=>ops.push(op),signal:abort.signal});
    const ev=p=>{const v=new THREE.Vector3(...toWorld(p)).project(camera);return {clientX:(v.x+1)*720,clientY:(1-v.y)*450};};
    try{
      // Drag {at:0} with corner 0 taken by another nearExact so it stays {at:0}.
      stubCands[0].nearExact=[{roof:'r',edge:0,index:1}];
      const h0=handles.handles().find(h=>h.spout==='b:r:0:0');assert.ok(h0);
      const baseEv=ev(h0.at);
      assert.ok(handles.begin(baseEv));
      handles.update({clientX:baseEv.clientX+4,clientY:baseEv.clientY});
      const after4=handles.handles().find(h=>h.spout==='b:r:0:0');
      assert.ok(Math.abs(after4.at[0]-(-2))<.05,`4 px move on {at:0} stays at exposed end -2, got ${after4.at[0]}`);
      await handles.finish();
      assert.equal(ops.length,0,'4 px move on {at:0} at overhang 2 stays {at:0} and commits nothing');
      // Item 6: off-centre grab (14 px off, 4 px move) on {at:0.6000012} + rounded original no-op check.
      n4Plan.buildings[0].roofs[0].edges[0].downspouts=[{at:0.6000012}];
      stubSnapshot={
        runs:[{id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:toWorld([0,0,roof.plate]),b:toWorld([40,0,roof.plate])}]}],
        spouts:[{id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:.6000012},top:toWorld([24.000048,-1.25,roof.plate]),
          source:'override',authoredFraction:.6000012,authoredIndex:0,exact:true,flags:[]}],
      };
      stubCands=[];
      const hAt=handles.handles().find(h=>h.spout==='b:r:0:0');assert.ok(hAt);
      const atEv=ev(hAt.at);
      const offGrab={clientX:atEv.clientX+14,clientY:atEv.clientY};
      // Zero move from 14 px off-centre compares against rounded original (0.6) -> commits nothing!
      assert.ok(handles.begin(offGrab));
      handles.update(offGrab);
      await handles.finish();
      assert.equal(ops.length,0,'zero move on unrounded {at:0.6000012} compares rounded original and commits nothing');
      // 4 px move from 14 px off-centre moves ~0.37 ft (~0.009), NOT 18 px (~0.042).
      assert.ok(handles.begin(offGrab));
      handles.update({clientX:atEv.clientX+18,clientY:atEv.clientY});
      await handles.finish();
      assert.equal(ops.length,1);
      assert.ok(ops[0].downspouts[0].at>0.602&&ops[0].downspouts[0].at<0.62,
        `expected ~0.609 for 4 px move from 14 px off-centre grab, got ${ops[0].downspouts[0].at}`);
      // Item 6: byAuthored skips exact spouts when resolving a numeric entry without authoredIndex.
      const dupPlan=structuredClone(plan);
      dupPlan.buildings[0].roofs[0].edges[0].downspouts=[.6,{at:.6}];
      stubSnapshot={
        runs:[{id:'b:r:0',building:'b',segments:[{roof:'r',edge:0,a:toWorld([0,0,roof.plate]),b:toWorld([40,0,roof.plate])}]}],
        spouts:[
          {id:'b:r:0:0',run:'b:r:0',edge:{roof:'r',edge:0,fraction:.6},top:toWorld([24,-1.25,roof.plate]),
            source:'override',authoredFraction:.6,exact:true,flags:[]},
          {id:'b:r:0:1',run:'b:r:0',edge:{roof:'r',edge:0,fraction:1},top:toWorld([40,-1.25,roof.plate]),
            source:'override',authoredFraction:.6,flags:[]},
        ],
      };
      assert.equal(placedFraction(dupPlan,'b','r',0,0,.6),1,'byAuthored skips exact spout for numeric entry');
    }finally{abort.abort();}
  }finally{stubSnapshot=prevSnap;stubCands=prevCands;}
});
await test('test_stub_checks_render_all_three_new_flag_texts',async()=>{
  const abort=new AbortController();
  const checks=createChecks({},{api:{op:async()=>{}},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,
    tools:{select(){},focusDownspout(){}},panel:{checks(){}},canEdit:()=>true,signal:abort.signal,
    flags:{dismiss(){},review(){}}});
  try{
    checks.show();
    const issue=checks.queue().find(i=>i.kind==='gutter'&&i.spout==='b:r:0:1');
    assert.ok(issue);
    assert.ok(issue.reason.includes('This downspout was placed by hand away from an outside corner.'));
    assert.ok(issue.reason.includes('This downspout passes a door or window.'));
    assert.ok(issue.reason.includes('This downspout has no wall or post to fasten to.'));
  }finally{abort.abort();}
});
finish();
"""


if __name__ == '__main__':
    plan = flatten(house())
    plan['buildings'][0]['levels'][0]['outline'] = plan['buildings'][0]['roofs'][0]['area']
    from services import twin_model_roofs
    samples = []
    for settings in [('sloped',) * 4, ('sloped', 'gable', 'gable', 'gable'),
                     ('sloped', 'gable', 'sloped', 'clip'), ('gable', 'sloped', 'clip', 'sloped')]:
        sample = house()
        roof = sample['buildings'][0]['roofs'][0]
        for edge, setting in zip(roof['edges'], settings):
            edge['setting'] = setting
        expected = sorted(twin_model_roofs.eave_edge_indices(roof))
        samples.append({'building': flatten(sample)['buildings'][0], 'expected': expected})
    from twin_awning_test_fixtures import migrated_awning_house
    payload = {'root': ROOT.as_posix(), 'plan': plan, 'eaves': samples,
               'awningPlan': migrated_awning_house()}
    code, output = run_node(DRIVER, payload)
    print(output, end='')
    if code:
        sys.exit(code)
    code2, output2 = run_node(STUB_DRIVER, payload)
    print(output2, end='')
    sys.exit(code2 or 0)
