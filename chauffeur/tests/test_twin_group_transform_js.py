"""Task 2 production group transforms/queue under node, using the household.

No browser. Run from chauffeur/: python tests/test_twin_group_transform_js.py.
"""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = r"""
const THREE = await import('three');
const {groupTransform, transformOperations, previewTransforms, deleteOperations, groupRecord, canTransform} = await import(file('static/twin/editor/group_transform.js'));
const {createGizmo} = await import(file('static/twin/editor/gizmo.js'));
const {applyLocal, LocalMissing} = await import(file('static/twin/editor/local_ops.js'));
const {createEditQueue} = await import(file('static/twin/editor/edit_queue.js'));
const {createHistory} = await import(file('static/twin/editor/history.js'));
const {createVisibility} = await import(file('static/twin/editor/visibility.js'));
const {groundAt} = await import(file('static/twin/twin_ground.js'));
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} near ${b}`);
let plan=structuredClone(input.flat);
const b=plan.buildings[0], bid=b.id;
const ref=(kind,pieceId,buildingId)=>({kind,pieceId,...(buildingId?{buildingId}:{})});
const plant=plan.site.planting[0], tree=ref('planting',plant.id), wall=ref('wall',b.walls[0].id,bid);
const opening=ref('opening',b.openings[0].id,bid), room=ref('room',b.rooms[0].id,bid);
const cases=[
 [tree,[true,true,true]], [wall,[true,true,false]], [opening,[true,false,true]],
 [room,[false,false,false]], ...['floor','roof','roof_plane','pool','building'].map(kind=>[ref(kind,kind,bid),[false,false,false]])
];
for(const [r,want] of cases) assert.deepEqual(['move','rotate','scale'].map(t=>!!canTransform(groupRecord(plan,r),t)),want,r.kind);
for(const kind of ['furniture','beds','hardscape','edges','fence','fire_pit','yard_rooms']) {
 plan.site[kind]=[{id:`test:${kind}`,polygon:[[0,0],[4,0],[4,4],[0,4]],at:[2,2]}];
 const r=groupRecord(plan,ref(kind,`test:${kind}`));
 assert.deepEqual(['move','rotate','scale'].map(t=>!!canTransform(r,t)),[true,true,true]);
}
plan.site.terraces=[{id:'pad',polygon:[[0,0],[4,0],[4,4],[0,4]],height:2}];
plan.site.pool={id:'pool',polygon:[[0,0],[20,0],[20,20],[0,20]],features:[{id:'spa',kind:'spa',polygon:[[1,1],[3,1],[3,3],[1,3]]}]};
assert.deepEqual(['move','rotate','scale'].map(t=>!!canTransform(groupRecord(plan,ref('spa','spa')),t)),[true,false,false]);
const fid='fixture:00000000-0000-4000-8000-000000000001',eid='effect:00000000-0000-4000-8000-000000000002';
plan.light_fixtures={'light.a':[{id:fid,shape:'area',ref:'absolute',at:[0,0,3],rotation_deg:0,size_ft:[2,2]}]};
plan.effect_fixtures=[{id:eid,shape:'line',ref:'absolute',path:[[0,0,0],[4,0,0]],type:'fire',facing:[0,0,1]}];
for(const r of [ref('terraces','pad'),ref('light_fixture',fid),ref('effect_fixture',eid)])
 assert.deepEqual(['move','rotate','scale'].map(t=>!!canTransform(groupRecord(plan,r),t)),r.kind==='terraces'?[true,true,true]:[true,true,false]);
// Bounds centre (not average origins), restricted to movable/unlocked members.
const t2={...plant,id:'tree:other',at:[20,0]}; plan.site.planting=[{...plant,at:[0,0]},t2];
const refs=[tree,ref('planting',t2.id),room];
const boxes=refs.slice(0,2).map((r,i)=>({...r,box:new THREE.Box3(new THREE.Vector3(i?5:-1,0,-1),new THREE.Vector3(i?9:1,2,1))}));
let group=groupTransform(plan,refs,'move',{boxes}); near(group.centre[0],4/.3048);near(group.centre[2],1/.3048);assert.equal(group.records.length,2);
assert.equal(groupTransform(plan,refs,'move',{isPickable:r=>r.pieceId!==t2.id}).records.length,1);
group=groupTransform(plan,refs,'rotate');
let ops=transformOperations(group,{angle:90}), preview=applyLocal(plan,{op:'batch',ops}).plan;
near(preview.site.planting[0].at[0],10);near(preview.site.planting[0].at[1],-10);
near(preview.site.planting[1].at[0],10);near(preview.site.planting[1].at[1],10);
assert.deepEqual(preview.buildings[0].rooms,plan.buildings[0].rooms,'immovable selected room unchanged');
group=groupTransform(plan,refs,'scale');ops=transformOperations(group,{factor:2});preview=applyLocal(plan,{op:'batch',ops}).plan;
assert.deepEqual(preview.site.planting.map(p=>p.at),[[-10,0],[30,0]]);assert.equal(preview.site.planting[0].scale,2);
assert.equal(plan.site.planting[0].scale,plant.scale,'input stays immutable');
// Scale previews keep the ground anchor fixed even when bounds pivot is above it.
const specs=previewTransforms(group,{factor:2},preview),treeBase=new THREE.Vector3(0,groundAt(plan,0,0)*.3048,0).applyMatrix4(specs[0].matrix);
near(treeBase.x,-10*.3048);near(treeBase.y,groundAt(preview,-10,0)*.3048);
// Queued transforms keep stable identities across an unrelated row deletion.
const reordered=structuredClone(plan);reordered.site.planting.unshift({...plant,id:'unselected',at:[-20,0]});
const intended=transformOperations(groupTransform(reordered,refs,'rotate'),{angle:15});reordered.site.planting.shift();
const rotated=applyLocal(reordered,{op:'batch',ops:intended}).plan;assert.equal(rotated.site.planting[0].rotation,15);assert.equal(rotated.site.planting[1].rotation,15);
const walls=b.walls.filter(w=>w.state!=='ghost').slice(0,2).map(w=>ref('wall',w.id,bid));
ops=transformOperations(groupTransform(plan,walls,'move'),{by:[2,3]});
assert.equal(ops.length,1);assert.equal(ops[0].op,'move_joints');
assert.equal(new Set(ops[0].joints.map(j=>j.joint)).size,ops[0].joints.length,'shared joints move once');
const jointPreview=applyLocal(plan,{op:'batch',ops}).plan;
assert.notDeepEqual(jointPreview.buildings[0].walls[0].from,plan.buildings[0].walls[0].from);
const w=b.walls.find(w=>w.id===b.openings[0].wall),d=w.to.map((v,i)=>v-w.from[i]),length=Math.hypot(...d);
const ba=(b.rotation||0)*Math.PI/180,worldBy=[(d[0]*Math.cos(ba)-d[1]*Math.sin(ba))/length*2,(d[0]*Math.sin(ba)+d[1]*Math.cos(ba))/length*2];
group=groupTransform(plan,[opening,tree],'move');ops=transformOperations(group,{by:worldBy});
near(ops.find(o=>o.id===opening.pieceId).at,b.openings[0].at+2);
ops=transformOperations(groupTransform(plan,[opening,tree],'scale'),{factor:1.2});
near(ops.find(o=>o.id===opening.pieceId).width,b.openings[0].width*1.2);
// Constraint-aware previews use exactly the operations' along-wall slide.
const perpendicular=[-worldBy[1],worldBy[0]],og=groupTransform(plan,[opening,tree],'move');
const oo=transformOperations(og,{by:perpendicular}),opreview=applyLocal(plan,{op:'batch',ops:oo}).plan;
const om=previewTransforms(og,{by:perpendicular},opreview).find(s=>s.pieceId===opening.pieceId).matrix;
assert.ok(om.elements.every(Number.isFinite));near(om.elements[12],0);near(om.elements[14],0);
const pg=groupTransform(plan,[ref('terraces','pad'),tree],'scale'),po=transformOperations(pg,{factor:2});
const pm=previewTransforms(pg,{factor:2},applyLocal(plan,{op:'batch',ops:po}).plan).find(s=>s.pieceId==='pad').matrix;
near(pm.elements[5],1,'pad height stays fixed');
plan.site.hardscape=[{id:'test:path',kind:'path',points:[[0,0],[10,0]],width:3,radius:1}];
const pathGroup=groupTransform(plan,[ref('hardscape','test:path'),tree],'scale');
const pathOps=transformOperations(pathGroup,{factor:2}),pathPreview=applyLocal(plan,{op:'batch',ops:pathOps}).plan;
assert.equal(pathPreview.site.hardscape[0].width,6,'footprint scaling includes path width');assert.equal(pathPreview.site.hardscape[0].radius,2);
// Selected wall hosts already carry selected props through a turn.
const tiny={buildings:[{id:'tiny',position:[0,0],levels:[{id:'L',elevation:0}],joints:[{id:'a',at:[0,0]},{id:'z',at:[10,0]}],walls:[{id:'w',level:'L',joints:['a','z'],from:[0,0],to:[10,0]}],rooms:[],items:[{id:'chair',host:{wall:'w',at:2,z:3}}],anchors:[]}],site:{}};
const tg=groupTransform(tiny,[ref('wall','w','tiny'),ref('item','chair','tiny')],'rotate');
const to=transformOperations(tg,{angle:90});assert.equal(to.some(o=>o.op==='move_hosted'),false,'hosted prop follows selected host once');
const tp=applyLocal(tiny,{op:'batch',ops:to}).plan;near(tp.buildings[0].items[0].position[0],5);near(tp.buildings[0].items[0].position[1],-3);
plan.site.devices=[{id:'device:yard',device:'linked-sensor',host:{yard_room:'room:yard'}}];
assert.equal(deleteOperations(plan,[ref('pool','pool'),ref('spa','spa')])[0].op,'delete_pool_feature');
assert.deepEqual(deleteOperations(plan,[ref('yard_rooms','room:yard'),ref('device','device:yard')])[0],{op:'unplace_device',device:'linked-sensor'});
assert.deepEqual(deleteOperations(plan,[...refs,ref('terraces','pad'),ref('light_fixture',fid)]).map(o=>o.op),['delete_site_item','delete_site_item','delete_pad','delete_light_fixture','delete']);
let notices=0,writes=0;
const visibility=createVisibility({storage:{getItem:()=>null,setItem:()=>writes++}});visibility.subscribe(()=>notices++);
visibility.setMembers(refs,{hidden:true,locked:true});assert.equal(notices,1);assert.equal(writes,1);assert.ok(refs.every(r=>visibility.isHidden(r.pieceId)&&visibility.isLocked(r.pieceId)));
// Actual gizmo rays, typing, cancel, one batch/release, and CPU drag frames.
plan=structuredClone(input.flat);plan.site.planting=Array.from({length:200},(_,i)=>({...structuredClone(plant),id:`tree:${i}`,at:[i%20*4,Math.floor(i/20)*4]}));
const members=plan.site.planting.map(p=>ref('planting',p.id));members.push(room);
const canvas=document.createElement('canvas'),layer=document.createElement('div');document.body.append(canvas,layer);
canvas.getBoundingClientRect=()=>({left:0,top:0,width:1000,height:1000});
const camera=new THREE.OrthographicCamera(-40,40,40,-40,.01,1000);camera.position.set(0,100,.001);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
const event=p=>{const v=new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048).project(camera);return {clientX:(v.x+1)*500,clientY:(1-v.y)*500,button:0};};
let sent=[],tool='move',dragFrames=0;
const view={camera,renderer3:{domElement:canvas},groups:{levels:{}},previewSelectionGroup(){dragFrames++;}};
const gizmo=createGizmo({view,layer,getPlan:()=>plan,getSelection:()=>({kind:'room',id:room.pieceId,building:bid}),getMembers:()=>members,getTool:()=>tool,op:()=>assert.fail('single op used'),applyBatch:async(ops,options)=>sent.push({ops,options})});
let h=gizmo.handles().find(h=>h.kind==='gizmo_move_x');assert.ok(h,'immovable primary does not suppress group gizmo');assert.ok(gizmo.begin(event(h.at),h));
const times=[];
for(let i=0;i<50;i++) {const start=performance.now();gizmo.update(event([h.at[0]+1+i/4,h.at[1],h.at[2]]),{free:true});times.push(performance.now()-start);assert.equal(sent.length,0);}
assert.equal(dragFrames,50);const max=Math.max(...times),p95=[...times].sort((a,b)=>a-b)[47];
assert.ok(max<33,`200-plant drag max ${max.toFixed(2)} ms <33 ms`);
await gizmo.commit(3);assert.equal(sent.length,1);assert.equal(sent[0].ops.length,200);near(sent[0].ops[0].at[0],3);
assert.ok(sent[0].options.local);assert.deepEqual(members.at(-1),room,'not movable remains selected');
tool='scale';h=gizmo.handles()[0];assert.equal(gizmo.handles().length,1,'uniform group scale only');gizmo.begin(event(h.at),h);gizmo.update(event(h.at.map((v,i)=>h.centre[i]+2*(v-h.centre[i]))));await gizmo.commit(2);assert.equal(sent.length,2);assert.equal(sent[1].ops.filter(o=>o.op==='set_object').length,200);
tool='rotate';h=gizmo.handles()[0];gizmo.begin(event(h.at),h);await gizmo.commit(90);assert.equal(sent.length,3);assert.equal(sent[2].ops.length,400);
h=gizmo.handles()[0];gizmo.begin(event(h.at),h);gizmo.update(event([h.at[0],h.at[1]+3,h.at[2]]));await gizmo.finish(true);assert.equal(sent.length,3);
// Queue refuses/drops the whole step when any member disappears on replay.
let rejects,release;const refused=new Promise((_,r)=>rejects=r),pending=new Promise(r=>release=r),changes=[];
const queue=createEditQueue({send:op=>op.op==='bad'?refused:pending,onChange:c=>changes.push(c)});
queue.base({round:1,plan});queue.push({op:{op:'bad'},label:'first'}).saved.catch(()=>{});
const batch={op:'batch',ops:[{op:'move_site_item',list:'planting',id:'tree:0',at:[100,0]},{op:'move_site_item',list:'planting',id:'tree:1',at:[100,4]}]};
const step=queue.push({op:batch,label:'whole group'});step.saved.catch(()=>{});assert.equal(queue.pending(),2);
const foreign=structuredClone(plan);foreign.site.planting.shift();queue.base({round:2,plan:foreign});assert.equal(queue.pending(),1,'one missing member drops batch');
assert.deepEqual(queue.shown(),foreign,'no partial member preview');rejects(Object.assign(new Error('window does not fit'),{status:400,member:1,reason:'window does not fit'}));
await new Promise(r=>setTimeout(r,0));assert.equal(queue.pending(),0);assert.deepEqual(changes.at(-1).dropped,['whole group']);
console.log(`PASS group kind table, rendered pivot, wall joints, opening slide/size, typed move/turn/scale, cancel, atomic queue; 200 plants max=${max.toFixed(3)}ms p95=${p95.toFixed(3)}ms`);
"""

# Reuse the real household editor mount and the document's capture/bubble event
# harness. This also runs Task 1's selection regression cases unchanged.
INTEGRATION = r"""
await test('group_scene_actions_and_outlines', async()=>{
  const ed=await mountEditor();
  try {
    const plants=ed.plan.site.planting.slice(0,2);
    const refs=plants.map(p=>({kind:'planting',pieceId:p.id}));
    ed.tools.selectionStore.set(refs);ed.tools.setTool('move');
    const h=ed.tools.gizmo.handles().find(h=>h.kind==='gizmo_move_x');assert.ok(h);
    const event=p=>{const v=new THREE.Vector3(p[0]*FT,p[2]*FT,-p[1]*FT).project(ed.view.camera),rect=ed.canvas.getBoundingClientRect();return {clientX:rect.left+(v.x+1)*rect.width/2,clientY:rect.top+(1-v.y)*rect.height/2,button:0};};
    assert.ok(ed.tools.gizmo.begin(event(h.at),h));
    const outlines=refs.map(r=>ed.visibleOutlineObjectsFor(r.pieceId).find(l=>l instanceof THREE.Box3Helper));
    assert.ok(outlines.every(Boolean),'real rendered outlines present');const before=outlines.map(l=>l.box.clone());
    ed.tools.gizmo.update(event([h.at[0]+2,h.at[1],h.at[2]]),{free:true});
    for(let i=0;i<outlines.length;i++)assert.ok(Math.abs(outlines[i].box.min.x-before[i].min.x-2*FT)<1e-6,'each rendered preview moves with set');
    assert.equal(ed.ops.length,0,'preview sends nothing');await ed.tools.gizmo.commit(2);
    assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].operation.op,'batch');assert.equal(ed.ops[0].operation.ops.length,2);
    assert.deepEqual(ed.tools.selectionStore.members().map(r=>r.pieceId),refs.map(r=>r.pieceId));
    ed.tools.openContextMenu({clientX:50,clientY:50},{kind:'planting',id:refs[0].pieceId});
    const menu=document.getElementById('editor-context-menu');const button=text=>[...menu.querySelectorAll('button')].find(b=>b.textContent===text);
    await fire(button('Hide'),'click');assert.ok(refs.every(r=>ed.visibility.isHidden(r.pieceId)));assert.equal(ed.ops.length,1);
    ed.visibility.showAll();
    ed.tools.openContextMenu({clientX:50,clientY:50},{kind:'planting',id:refs[0].pieceId});await fire(button('Lock'),'click');assert.ok(refs.every(r=>ed.visibility.isLocked(r.pieceId)));assert.equal(ed.ops.length,1);
    assert.equal(ed.tools.selectionStore.members().length,2);assert.equal(ed.tools.gizmo.handles().length,0,'locked set cannot transform');
    ed.visibility.setMembers(refs,{locked:false});window.promptConfirm=async()=>true;
    await ed.tools.deleteSelected();assert.equal(ed.ops.length,2);assert.equal(ed.ops[1].operation.op,'batch');assert.equal(ed.ops[1].operation.ops.length,2);
    assert.equal(ed.tools.selectionStore.members().length,0);
    // Delegated primary cards must route Delete through the same set action.
    const extra=[{kind:'terraces',pieceId:ed.plan.site.terraces[0].id},{kind:'light_fixture',pieceId:'fix:yard-1',entity_id:'light.yard'},{kind:'effect_fixture',pieceId:'eff:yard-1'}];
    ed.tools.setTool('select');
    for(const r of extra) {
      ed.tools.selectionStore.set([refs[0],r]);
      const card=r.kind==='terraces'?document.getElementById('terrain-card'):ed.dom.pieceCard;
      assert.equal(card.hidden,false,`${r.kind} card visible`);
      const count=ed.ops.length,del=[...card.querySelectorAll('button')].find(b=>b.textContent==='Delete');assert.ok(del,`${r.kind} Delete card mounted`);
      await fire(del,'click');await new Promise(r=>setTimeout(r,10));
      assert.equal(ed.ops.length,count+1,`${r.kind} card sends once`);assert.equal(ed.ops.at(-1).operation.op,'batch');assert.equal(ed.ops.at(-1).operation.ops.length,2);
    }
    // Ctrl/Cmd must still toggle a selected body with every transform tool.
    const b=ed.plan.buildings.find(b=>b.id==='pool-house'),walls=b.walls.filter(w=>w.level==='L1'&&w.kind!=='separator'&&w.state!=='ghost');
    ed.view.setView(`${b.id}:L1`);
    const avg=[0,1].map(i=>walls.reduce((s,w)=>s+(w.from[i]+w.to[i])/2,0)/walls.length);ed.look([...avg,0],b,90);
    const mid=w=>[(w.from[0]+w.to[0])/2,(w.from[1]+w.to[1])/2,4];
    const pickable=walls.filter(w=>ed.view.pick(...ed.pixel(mid(w),b))?.id===w.id);assert.ok(pickable.length>=2);
    for(const tool of ['move','rotate','scale']) {
      const set=pickable.slice(0,2).map(w=>({kind:'wall',pieceId:w.id,buildingId:b.id}));ed.tools.selectionStore.set(set);ed.tools.setTool(tool);
      const count=ed.ops.length;await ed.clickAt(ed.pixel(mid(pickable[0]),b),{ctrlKey:true});
      assert.equal(ed.tools.selectionStore.has(set[0]),false,`${tool} Ctrl-click removes member`);assert.equal(ed.tools.selectionStore.has(set[1]),true);assert.equal(ed.ops.length,count);
    }
  } finally {ed.dispose();}
});
await test('real_household_200_plant_view_drag_budget',async()=>{
  const plan=makeHousehold(),source=plan.site.planting.find(p=>p.state!=='ghost');
  plan.site.planting=Array.from({length:200},(_,i)=>({...structuredClone(source),id:`budget:plant:${i}`,at:[source.at[0]+i%20,source.at[1]+Math.floor(i/20)]}));
  const ed=await mountEditor(plan);
  try {
    const refs=plan.site.planting.map(p=>({kind:'planting',pieceId:p.id}));ed.tools.selectionStore.set(refs);ed.tools.setTool('move');
    const h=ed.tools.gizmo.handles().find(h=>h.kind==='gizmo_move_x');assert.ok(h);
    const event=p=>{const v=new THREE.Vector3(p[0]*FT,p[2]*FT,-p[1]*FT).project(ed.view.camera),r=ed.canvas.getBoundingClientRect();return {clientX:r.left+(v.x+1)*r.width/2,clientY:r.top+(1-v.y)*r.height/2,button:0};};
    assert.ok(ed.tools.gizmo.begin(event(h.at),h));
    const times=[];for(let i=0;i<30;i++){const start=performance.now();ed.tools.gizmo.update(event([h.at[0]+1+i/4,h.at[1],h.at[2]]),{free:true});times.push(performance.now()-start);assert.equal(ed.ops.length,0);}
    const max=Math.max(...times),p95=[...times].sort((a,b)=>a-b)[28];assert.ok(max<33,`200 real view plant outlines max ${max.toFixed(3)}ms <33ms`);
    await ed.tools.gizmo.commit(3);assert.equal(ed.ops.length,1);assert.equal(ed.ops[0].operation.op,'batch');assert.equal(ed.ops[0].operation.ops.length,200);
    console.log(`COST real household view 200 plants max=${max.toFixed(3)}ms p95=${p95.toFixed(3)}ms`);
  } finally {ed.dispose();}
});
"""

def check_editor_batch_path():
    """Exercise applyBatch's real boot, queue, request, status and history."""
    import re
    from test_twin_editor_history_js import DRIVER as HISTORY_DRIVER, STUBS
    from twin_live_node_rig import run
    driver = HISTORY_DRIVER.split(' const zoneResize=')[0].replace(
        "if(path==='editor/state')", "if(path.startsWith('editor/state'))").replace(
        "if(op.op==='refuse')", "if(op.op==='batch'&&op.ops.some(o=>o.id==='missing'))return response(400,{error:'Batch member 2 (missing) refused: This window no longer fits.',member:1,reason:'This window no longer fits.'});if(op.op==='refuse')").replace(
        "else assert.fail('unexpected mutation '+JSON.stringify(op));",
        "else if(op.op==='batch')plan=(await import(file('static/twin/editor/local_ops.js'))).applyLocal(plan,op).plan;else assert.fail('unexpected mutation '+JSON.stringify(op));")
    driver += r"""
 plan.site.furniture=[{id:'a',at:[0,0]},{id:'b',at:[10,0]}];saved.set(0,structuredClone(plan));
 window.dispatchEvent(new Event('focus'));await wait(20);
 assert.equal(typeof hooks.applyBatch,'function');
 const ops=[{op:'move_site_item',list:'furniture',id:'a',at:[2,0]},{op:'move_site_item',list:'furniture',id:'b',at:[12,0]}];
 await hooks.applyBatch(ops);await wait(30);
 assert.equal(writes.length,1);assert.equal(writes[0].op.op,'batch');assert.deepEqual(writes[0].op.ops,ops);
 assert.deepEqual(plan.site.furniture.map(p=>p.at),[[2,0],[12,0]]);
 await press(document.getElementById('rail-undo'));await until(()=>reverts.length===1&&!document.getElementById('rail-redo').disabled);
 assert.deepEqual(plan.site.furniture.map(p=>p.at),[[0,0],[10,0]]);
 await press(document.getElementById('rail-redo'));await until(()=>reverts.length===2&&!document.getElementById('rail-undo').disabled);
 assert.deepEqual(plan.site.furniture.map(p=>p.at),[[2,0],[12,0]]);
 const error=await hooks.applyBatch([ops[0],{...ops[1],id:'missing'}]).then(()=>assert.fail('must refuse'),e=>e);
 assert.equal(error.member,1);assert.equal(error.reason,'This window no longer fits.');
 assert.match(document.getElementById('editor-status').textContent,/missing.*window no longer fits/);
 assert.equal(alerts.length,1);assert.deepEqual(plan.site.furniture.map(p=>p.at),[[2,0],[12,0]]);
 assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
 window.dispatchEvent(new Event('pagehide'));console.log('PASS real editor applyBatch queue, single undo/redo, refusal member and status');process.exit(0);
 }catch(error){console.error(error);process.exit(1);}
"""
    ids = sorted(set(re.findall(r'id="([\w-]+)"', (ROOT / 'templates/house_editor.html').read_text(encoding='utf8'))) | {'piece-card', 'rail-undo', 'rail-redo', 'rail-add-effect', 'editor-save-state'})
    return run(driver, {'stubs': STUBS, 'ids': ids}, timeout=60)

if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'))
    kit['manifest'] = {}
    payload = {'root': ROOT.as_posix(), 'flat': flat, 'kit': kit,
               'objectSchema': json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf8'))}
    code, output = run_node(PRELUDE + DRIVER, payload, timeout=180)
    print(output)
    if code:
        sys.exit(code)
    from test_twin_selection_js import DRIVER as SELECTION_DRIVER
    code, output = run_node(SELECTION_DRIVER.rsplit('finish();', 1)[0] + INTEGRATION + '\nfinish();', payload, timeout=240)
    print(output)
    if code:
        sys.exit(code)
    sys.exit(check_editor_batch_path() or 0)
