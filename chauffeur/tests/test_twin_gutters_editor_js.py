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
      {op:'set_roof_edge',building:'b',roof:'r',edge:0,gutter:false,downspouts:[]},
      {op:'set_roof_edge',building:'b',roof:'r',edge:0,setting}]});
  }
});
await test('test_drag_writes_fraction_override',async()=>{
  setup();roof().edges[0].gutter=true;
  // Exercise rotation and translation, not just axis-aligned screen coordinates.
  plan.buildings[0].rotation=31;plan.buildings[0].position=[7,-4];
  const rig=handleRig();try{
    const h=rig.handles.handles().find(h=>h.kind==='downspout');assert.ok(h,'generated downspout handle');
    const actual=spouts()[0], b=plan.buildings[0], a=-b.rotation*Math.PI/180;
    const x=actual.top[0]/.3048-b.position[0],y=-actual.top[2]/.3048-b.position[1];
    assert.ok(Math.hypot(h.at[0]-(Math.cos(a)*x-Math.sin(a)*y),h.at[1]-(Math.sin(a)*x+Math.cos(a)*y))<1e-6);
    assert.ok(rig.handles.begin(rig.event(h.at)));
    const from=roof().area[0],to=roof().area[1],target=[from[0]+.65*(to[0]-from[0]),from[1]+.65*(to[1]-from[1]),h.at[2]];
    rig.handles.update(rig.event(target));assert.equal(ops.length,0);await rig.handles.finish();
    assert.equal(ops.length,1);assert.equal(ops[0].op,'set_roof_edge');assert.equal(ops[0].edge,0);
    assert.ok(ops[0].downspouts.some(t=>Math.abs(t-.65)<.002),JSON.stringify(ops));
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
await test('test_add_disabled_at_8',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=Array.from({length:8},(_,i)=>i/7);edge(0);
  const add=button('Add downspout');assert.ok(add);assert.equal(add.disabled,true);
  cards.draw();assert.equal(button('Add downspout').disabled,true,'poll keeps capacity disabled');
  setup();roof().edges[0].gutter=true;edge(0);await press('Add downspout');
  assert.equal(ops.length,1);assert.ok(ops[0].downspouts.length>=2&&ops[0].downspouts.length<=8);
  assert.ok(ops[0].downspouts.every(t=>t>=0&&t<=1));
});
await test('test_reset_clears_override',async()=>{
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[];edge(0);await press('Reset to automatic');
  assert.deepEqual(ops,[{op:'set_roof_edge',building:'b',roof:'r',edge:0,downspouts:null}]);
});
await test('test_check_list_lists_each_flag_with_reason',async()=>{
  const {gutterCheckItems}=await import(file('static/twin/editor/gutter_controls.js'));
  const {createChecks}=await import(file('static/twin/editor/checks.js'));
  setup();const flags=['no-outside-corner','hang','stub','inner-end','clipped-end','no-safe-landing','no-outlet','outlet-blocked','merged-override'];
  const run={id:'b:r:0',building:'b',segments:[{roof:'r',edge:0}],flags:['no-outside-corner']};
  const spout={id:'b:r:0:0',run:run.id,edge:{roof:'r',edge:0,fraction:.1},top:[0,3,0],flags,
    merged:[{run:'b:other:2',fraction:.75},{run:'b:other:3',fraction:.25}]};
  const items=gutterCheckItems(plan,{runs:[run],spouts:[spout]});
  for(const flag of flags){const item=items.find(i=>i.flag===flag);assert.ok(item,flag);assert.ok(item.reason.length>15);assert.ok(!item.reason.includes('\n'));assert.equal(item.roof,'r');}
  const merged=items.find(i=>i.flag==='merged-override');for(const text of ['b:other:2','0.75','b:other:3','0.25'])assert.ok(merged.reason.includes(text),merged.reason);
  // Real Check queue consumes builder output and opens the selected roof/downspout.
  roof().edges[0].gutter=true;plan.buildings[0].levels[0].outline=[];
  const selected=[],focused=[],abort=new AbortController();
  const checks=createChecks({},{api:{op:async()=>{},report:e=>{throw e;}},getBuild:()=>null,getModel:()=>plan,getPlan:()=>plan,
    tools:{select:r=>selected.push(r),focusDownspout:r=>focused.push(r)},panel:{checks(){}},canEdit:()=>true,signal:abort.signal,
    flags:{dismiss(){},review(){}},dock:{properties:{clear(){},render(){}}}});
  const entry=checks.queue().find(i=>i.kind==='gutter');assert.ok(entry,'Check queue contains gutter issues');checks.show(entry);
  const row=document.getElementById('check-card').querySelector('[data-gutter-check]');assert.ok(row,'clickable list of gutter checks');
  click(row);await tick();assert.ok(selected.some(r=>r.id==='r'||r.pieceId==='r'));assert.ok(focused.length);
  abort.abort();
});
await test('test_porch_and_awning_toggle',async()=>{
  const {sceneRows}=await import(file('static/twin/editor/scene_tree.js'));
  for(const kind of ['porch','awning']){
    setup();const b=plan.buildings[0],p={id:kind,kind,level:'L1',polygon:[[0,0],[8,0],[8,4],[0,4]],floor:0,roof:{kind:'shed',height:8}};
    if(kind==='porch')b.porches=[p];else b.roof.extensions=[p];
    assert.ok(sceneRows(plan).some(r=>r.id===kind),'attachment is reachable in Scene');
    cards.draw({pieceId:kind,buildingId:'b'});await toggle();
    assert.deepEqual(ops,[{op:'set',building:'b',id:kind,field:'gutter',value:true}]);
  }
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


if __name__ == '__main__':
    plan = flatten(house())
    plan['buildings'][0]['levels'][0]['outline'] = plan['buildings'][0]['roofs'][0]['area']
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(output, end='')
    sys.exit(code or 0)
