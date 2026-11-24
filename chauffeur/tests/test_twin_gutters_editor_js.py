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
  setup();roof().edges[0].gutter=true;roof().edges[0].downspouts=[0];edge(0);await press('Add downspout');
  assert.equal(ops.length,1);assert.equal(ops[0].downspouts.length,2);assert.ok(ops[0].downspouts[1]>.9,'adds the other free corner');
  assert.ok(ops[0].downspouts.every(t=>t>=0&&t<=1));
  setup();roof().edges[0].gutter=true;edge(0);assert.equal(button('Add downspout').disabled,true);
  assert.match(button('Add downspout').title,/no free/i);
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
    if(kind==='porch')b.porches=[p];else b.roof.extensions=[p];
    assert.ok(sceneRows(plan).some(r=>r.id===kind),'attachment is reachable in Scene');
    cards.draw({pieceId:kind,buildingId:'b'});await toggle();
    assert.deepEqual(ops,[{op:'set',building:'b',id:kind,field:'gutter',value:true}]);
  }
});
await test('test_awning_scene_row_omits_ineffective_eye',async()=>{
  setup();const {createSceneTree}=await import(file('static/twin/editor/scene_tree.js'));
  plan.buildings[0].roof.extensions=[{id:'shade',kind:'awning',section:'r',level:'L1',name:'Entry awning'}];
  const treeHost=document.createElement('div');document.body.append(treeHost);
  const tree=createSceneTree({host:treeHost,getPlan:()=>plan,getSelection:()=>null,select(){},floors:{current:()=> 'b:L1',hidden:()=>false}});
  const row=treeHost.querySelector('[data-scene-id="shade"]');assert.ok(row);
  assert.equal(row.querySelector('[data-row-eye]'),null);assert.ok(row.querySelector('[data-scene-select]'));tree.dispose();treeHost.remove();
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
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'eaves': samples})
    print(output, end='')
    sys.exit(code or 0)
