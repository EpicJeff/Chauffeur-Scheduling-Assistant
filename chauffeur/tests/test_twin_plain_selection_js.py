"""Plain selection/focus and merged live previews: production modules, Node only."""
from pathlib import Path
import json
import subprocess
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const T=await import('three');
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createRoomSelection,createSelection}=await import(file('static/twin/editor/selection.js'));
const {createMarquee}=await import(file('static/twin/editor/marquee.js'));
const {selectUsingMaterial}=await import(file('static/twin/editor/selection_materials.js'));
const {createDrag}=await import(file('static/twin/editor/drag.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {buildAtlas,prepareReceivers}=await import(file('static/twin/bake/atlas.js'));
const {materialParts}=await import(file('static/twin/bake/bindings.js'));
const {isBakeRoot}=await import(file('static/twin/bake/source.js'));
const {bakeLayout}=await import(file('static/twin/bake/baker.js'));
const {createSelectionFocus}=await import(file('static/twin/selection_focus.js'));
const createSelectionFocusForTest=()=>createSelectionFocus({render:()=>{}});
globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
const square=[[0,0],[12,0],[12,10],[0,10]],FT=.3048;
function building(id,x=0){return {id,position:[x,0],levels:[{id:'L1',elevation:0,ceiling:8,outline:square}],
 joints:square.map((at,i)=>({id:'j'+i,level:'L1',at})),
 walls:square.map((from,i)=>({id:'w'+i,level:'L1',from,to:square[(i+1)%4],joints:['j'+i,'j'+((i+1)%4)],height:8,thickness:.5,exterior:true,state:'settled'})),
 rooms:[{id:'r',kind:id==='b'?'porch':'room',level:'L1',polygon:square,joints:['j0','j1','j2','j3'],state:'settled'}],
 openings:[{id:'o',wall:'w0',at:5,width:2,sill:2,head:6,kind:'window',state:'settled'}],
 anchors:[{id:'a',kind:'sensor',host:{wall:'w0',side:'left',at:8,z:4},visible_in:['editor'],state:'settled'}],
 lights:[{id:'lamp',level:'L1',at:[4,4],kind:'recessed',visible_in:['editor']}],items:[],roof:{sections:[]}};}
async function setup(edit=()=>{}, anchors=false, tier='low', bake=false){const plan={buildings:[building('b'),building('c',30)],site:{},materials:{}};
 edit(plan);
 const shell=new Element(),host=new Element();shell.className='editor-shell';shell.append(host);
 const view=await mountTwin(host,{plan,kit:{materials:{}},tier,bake,preserveCamera:true});
 while(!view.ready)await new Promise(r=>setTimeout(r,1));
 if(anchors){view.showAnchors=true;await view.rebuild(plan);}
 const controller=createRoomSelection({view,getModel:()=>plan});
 return {view,controller,plan};}
await test('plain_room_porch_level_other_building_are_outline_only',async()=>{
 const {view:v,controller:s}=await setup();try{
 let rebuilds=0,clones=0,compiles=0;v.rebuild=()=>{rebuilds++;return Promise.resolve();};
 const clone=T.Material.prototype.clone;T.Material.prototype.clone=function(){clones++;return clone.call(this);};
 const compile=v.renderer3.compileAsync;v.renderer3.compileAsync=(...a)=>{compiles++;return compile?.(...a);};
 try{for(const pick of [{kind:'room',id:'r',building:'b',level:'L1'},{kind:'level',id:'L1',building:'b',level:'L1'},{kind:'room',id:'r',building:'c',level:'L1'}]){
 s.select(pick);assert.equal(s.current().room,null);assert.ok(s.inside({id:'w0',building:pick.building==='b'?'c':'b'}));
 assert.equal(v.selectionFloor(),pick.building+':L1');
 }s.clear();await v.setEditableLevel('b:L1');await v.setEditableLevel(null);
 assert.equal(rebuilds,0);assert.equal(clones,0);assert.equal(compiles,0);
 }finally{T.Material.prototype.clone=clone;v.renderer3.compileAsync=compile;}
 }finally{v.dispose();}
});
await test('focus_room_and_level_enter_leave_without_rebuilding',async()=>{
 const {view:v,controller:s}=await setup();try{
 let n=0;v.rebuild=()=>{n++;return Promise.resolve();};
 s.select({kind:'room',id:'r',building:'b',level:'L1'});s.focusRoom('r','b');await v.selectionReady;
 assert.equal(s.current().room,'r');assert.ok(!s.inside({id:'w0',building:'c'}));
 assert.ok(s.inside({id:'o',building:'b'}));
 s.leaveRoom();assert.equal(s.current().room,null);
 s.focusRoom({kind:'level',id:'L1',building:'b',level:'L1'});await v.selectionReady;
 assert.equal(s.current().room,'L1');assert.ok(s.inside({id:'w0',building:'b'}));s.leaveRoom();
 assert.equal(s.current().room,null);assert.equal(n,0);
 }finally{v.dispose();}
});
await test('focus_does_not_add_or_reveal_hidden_geometry_or_lights',async()=>{
 const {view:v,controller:s}=await setup();try{
 const hidden=()=>{const out=[];v.scene.traverse(o=>{if(o.isMesh&&['a','lamp'].includes(o.userData.pieceId))out.push(o);});return out;};
 const baseline=hidden();assert.equal(baseline.length,0,'viewer-only geometry stays absent with anchors disabled');
 s.select({kind:'room',id:'r',building:'b',level:'L1'});assert.ok(hidden().every(o=>!o.visible));
 s.focusRoom('r','b');await v.selectionReady;assert.deepEqual(hidden(),baseline);
 s.leaveRoom();assert.ok(hidden().every(o=>!o.visible));
 }finally{v.dispose();}
});
await test('focus_partitions_shared_batches_by_owner_and_restores_them',async()=>{
 const {view:v,controller:s,plan}=await setup();try{
 const p=structuredClone(plan);p.buildings[0].rooms.push({id:'outside',level:'L1',polygon:[[14,0],[20,0],[20,10],[14,10]],state:'settled'});
 await v.rebuild(p);const batches=[];v.scene.traverse(o=>{
  const ids=new Set(o.userData.snapRanges?.map(r=>r.pieceId));if(ids.has('r')&&ids.has('outside'))batches.push(o);
 });assert.ok(batches.length,'two room floors share a real material batch');
 const originals=batches.map(o=>({geometry:o.geometry,material:o.material,groups:o.geometry.groups}));
 s.focusRoom('r','b');await v.selectionReady;
 batches.forEach((o,i)=>{
  assert.equal(o.geometry,originals[i].geometry,'focus never copies or unmerges geometry');
  for(const range of o.userData.snapRanges.filter(r=>['r','outside'].includes(r.pieceId))){
   const group=o.geometry.groups.find(g=>g.start<=range.start&&g.start+g.count>=range.start+range.count);assert.ok(group);
   const m=o.material[group.materialIndex];
   assert.equal(!!m.userData.styledFade,range.pieceId==='outside');
   if(range.pieceId==='outside')assert.equal(m.opacity,.25);else assert.ok(m.userData.selectionTint);
  }
 });
 s.leaveRoom();batches.forEach((o,i)=>{assert.equal(o.material,originals[i].material);assert.equal(o.geometry.groups,originals[i].groups);});
 }finally{v.dispose();}
});
await test('first_focus_compiles_behind_normal_picture_and_late_completion_cannot_restore_focus',async()=>{
 const {view:v,controller:s}=await setup();try{
 const objects=[];v.scene.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31))objects.push([o,o.material]);});
 let finish;v.compileModelMaterials=()=>new Promise(resolve=>{finish=resolve;});
 s.focusRoom('r','b');const pending=v.selectionReady;assert.ok(finish);
 assert.ok(objects.every(([o,m])=>o.material===m),'ordinary materials draw during compile');
 s.leaveRoom();finish();await pending;
 assert.ok(objects.every(([o,m])=>o.material===m),'cancelled focus never adopts a late material');
 }finally{v.dispose();}
});
await test('room_and_level_cards_expose_explicit_focus_and_leave_actions',async()=>{
 const {view:v,plan}=await setup(p=>{p.buildings[1].porch={id:'legacy',polygon:[[14,0],[18,0],[18,4],[14,4]],floor:0,columns:[]};});let cards;let editable=true;const host=document.createElement('aside');host.id='piece-card';document.body.append(host);
 let selected;const s=createRoomSelection({view:v,getModel:()=>plan,onChange:()=>cards?.draw(selected)});
 try{
 cards=createCards({getPlan:()=>plan,getModel:()=>plan,getLabel:()=> 'Selected',getSelection:s.current,
  canEdit:()=>editable,select:p=>s.select(p),edit:()=>{},op:()=>{},ask:()=>{},
  focusRoom:p=>s.focusRoom(p),leaveRoom:s.leaveRoom});
 const button=label=>host.querySelectorAll('button').find(b=>b.textContent===label);
 for(const writable of [true,false])for(const pick of [{kind:'room',id:'r',building:'c',level:'L1'},{kind:'porch',id:'legacy',building:'c',level:'L1'},{kind:'level',id:'L1',building:'c',level:'L1'}]){
  editable=writable;
  selected={pieceId:pick.id,buildingId:pick.building};s.select(pick);cards.draw(selected);
  assert.ok(button('Focus room'));assert.equal(button('Focus room').disabled,false);assert.equal(s.current().room,null);
  button('Focus room').click();await Promise.resolve();await v.selectionReady;assert.equal(s.current().room,pick.id);
  assert.ok(button('Leave room'));button('Leave room').click();await Promise.resolve();assert.equal(s.current().room,null);assert.ok(button('Focus room'));
 }
 }finally{cards?.dispose();host.remove();v.dispose();}
});
await test('focus_keeps_authored_bake_key_and_receivers',async()=>{
 const keys=[],counts=[];
 for(const focused of [false,true]){
  const {view:v,controller:s,plan}=await setup();try{
   if(focused){s.focusRoom('r','b');await v.selectionReady;}
   const p=structuredClone(plan);p.buildings[1].name='Rebuilt neighbor';await v.rebuild(p);await v.selectionReady;
   const atlas=buildAtlas(v.scene.children.find(isBakeRoot),v.plan,{room:{density:1,page:256,gutter:2}});
   keys.push(atlas.key);counts.push(atlas.room.charts.reduce((n,c)=>n+materialParts(c).length,0));
  }catch(error){throw Error(error.stack);}finally{v.dispose();}
 }
 assert.equal(keys[0],keys[1]);assert.ok(counts[0]>0);assert.equal(counts[0],counts[1]);
});
await test('atlas_clipping_rebases_live_batch_ownership',()=>{
 const root=new T.Group(),geometry=new T.BufferGeometry();
 geometry.setAttribute('position',new T.Float32BufferAttribute([0,8,0, 128,8,-128, 128,8,0, 0,8,0, 0,8,-128, 128,8,-128],3));
 geometry.computeVertexNormals();
 const ranges=[{start:0,count:3,buildingId:'b',pieceId:'left'},{start:3,count:3,buildingId:'b',pieceId:'right'}];
 geometry.userData.snapRanges=ranges;
 const material=new T.MeshStandardMaterial({name:'roof'}),mesh=new T.Mesh(geometry,material);
 mesh.userData.merged=true;mesh.userData.snapRanges=ranges;root.add(mesh);
 prepareReceivers(root,{buildings:[building('b')],site:{}});
 assert.ok(mesh.geometry.attributes.position.count>6,'real atlas split the 128 ft faces');
 const rebased=mesh.userData.snapRanges;assert.equal(rebased,mesh.geometry.userData.snapRanges);
 assert.deepEqual(rebased.map(r=>r.pieceId),['left','right']);
 assert.equal(rebased[0].start,0);assert.equal(rebased[1].start,rebased[0].count);
 assert.equal(rebased[1].start+rebased[1].count,mesh.geometry.attributes.position.count);
 mesh.geometry.dispose();material.dispose();
});
await test('marquee_and_material_scope_are_independent_of_plain_camera_framing',async()=>{
 const {view:v,controller:s,plan}=await setup();try{
 v.setView('ext');s.select({kind:'room',id:'r',building:'b',level:'L1'});
 assert.equal(v.selectionFloor(),'b:L1');assert.equal(v.interactionFloor(),'ext');
 const members=createSelection(),marquee=createMarquee({view:v,selection:members,getPlan:()=>plan,isEmpty:()=>true});
 const box=()=>{marquee.pointerDown({clientX:-1e6,clientY:-1e6,button:0});marquee.pointerMove({clientX:1e6,clientY:1e6});marquee.pointerUp({clientX:1e6,clientY:1e6});};
 box();assert.ok(members.members().some(r=>r.buildingId==='c'),'plain room selection does not limit marquee to its floor');
 const p=structuredClone(plan);p.materials={siding:{id:'shared_finish'}};
 assert.ok(selectUsingMaterial(p,'shared_finish',{view:v}).some(r=>r.buildingId==='c'));
 s.focusRoom('r','b');await v.selectionReady;box();assert.ok(members.members().every(r=>r.buildingId==='b'));
 assert.ok(selectUsingMaterial(p,'shared_finish',{view:v}).every(r=>r.buildingId==='b'));
 marquee.dispose();
 }finally{v.dispose();}
});
await test('plain_picks_remain_unrestricted_and_top_plan_frame_selected_room',async()=>{
 const {view:v,controller:s}=await setup(p=>{p.buildings[1].rooms[0].polygon=[[2,2],[6,2],[6,6],[2,6]];});try{
 s.select({kind:'room',id:'r',building:'b',level:'L1'});
 v.setView('ext');v.setCameraState({position:[34*FT,20*FT,-4.999*FT],target:[34*FT,0,-5*FT]});
 assert.ok(v.pickAll(720,450).some(p=>p.building==='c'),'another building can be picked');
 s.focusRoom('r','b');await v.selectionReady;assert.equal(v.pickAll(720,450).length,0);s.leaveRoom();
 assert.ok(v.pickAll(720,450).some(p=>p.building==='c'));
 s.select({kind:'room',id:'r',building:'c',level:'L1'});
 v.setView('c:L1');v.setTopCamera(v.selectionFloor());
 assert.ok(Math.abs(v.controls.target.x/FT-34)<.01);assert.ok(Math.abs(v.controls.target.z/FT+4)<.01);
 v.setPlanCamera(v.selectionFloor());assert.ok(v.camera.isOrthographicCamera);assert.equal(v.selectionFloor(),'c:L1');
 assert.ok(Math.abs(v.controls.target.x/FT-34)<.01);
 }finally{v.dispose();}
});
function drawn(v,bid,id){const out=[];v.scene.traverse(o=>{
 if(!o.isMesh||o.layers.isEnabled(31)||!o.geometry?.attributes.position)return;
 const p=o.geometry.attributes.position,rs=o.userData.snapRanges;
 for(const r of rs||[{buildingId:o.userData.buildingId,pieceId:o.userData.pieceId,start:0,count:p.count}])
 if(r.buildingId===bid&&r.pieceId===id)out.push(...p.array.slice(r.start*3,(r.start+r.count)*3));
 });return out;}
for(const kind of ['wall','joint'])await test(kind+'_drag_without_focus_matches_focused_operations_and_merged_preview',async()=>{
 const results=[];
 for(const focused of [false,true]){
 const {view:v,controller:s,plan}=await setup();try{
 if(focused){s.focusRoom('r','b');await v.selectionReady;}
 const id=kind==='wall'?'w1':'j2',selection={kind,id,building:'b',level:'L1'};
 const before=drawn(v,'b','w1'),other=drawn(v,'c','w1'),previews=[],operations=[];
 let rebuilds=0;v.rebuild=()=>{rebuilds++;throw Error('full rebuild during drag');};
 const drag=createDrag({view:v,model:()=>plan,onPreview:p=>previews.push(p),onCommit:op=>operations.push(op)});
 const start=kind==='wall'?[12,5]:[12,10];assert.ok(drag.begin(selection,start));
 assert.ok(drag.update([start[0]+2,start[1]],{free:true}));
 assert.ok(previews.length);assert.notDeepEqual(drawn(v,'b','w1'),before);assert.deepEqual(drawn(v,'c','w1'),other);
 await drag.finish();assert.equal(rebuilds,0);assert.equal(operations.length,1);
 results.push({op:operations[0],wall:previews.at(-1).buildings[0].walls.find(w=>w.id==='w1')});
 }finally{v.dispose();}}
 assert.deepEqual(results[0],results[1]);
});
for(const kind of ['opening','anchor'])await test(kind+'_drag_without_focus_matches_focused_operations_and_preview',async()=>{
 const results=[];
 for(const focused of [false,true]){
 const {view:v,controller:s,plan}=await setup(undefined,true);const abort=new AbortController();try{
 if(focused){s.focusRoom('r','b');await v.selectionReady;}
 // A visible hand-placed anchor exercises hosted preview independently of focus.
 v.setView('b:L1');v.setCameraState({position:[6*FT,5*FT,12*FT],target:[6*FT,4*FT,0]});
 const id=kind==='opening'?'o':'a',selection={kind,id,building:'b',level:'L1'},ops=[],previews=[];
 const handles=createHandles({view:v,getPlan:()=>plan,getSelection:()=>selection,getTool:()=> 'move',canEdit:()=>true,
 drag:{},onCommit:op=>ops.push(op),onPreview:p=>previews.push(p),signal:abort.signal});
 const descriptor=handles.handles().find(h=>h.kind===(kind==='opening'?'opening_middle':'hosted'));
 assert.ok(descriptor,'real handle available without room focus');
 const pixel=p=>{const q=new T.Vector3(p[0]*FT,p[2]*FT,-p[1]*FT).project(v.camera);return {clientX:(q.x+1)*720,clientY:(1-q.y)*450};};
 const h=handles.hit(pixel(descriptor.at));assert.ok(h);
 const before=drawn(v,'b',id),other=drawn(v,'c','w1');
 let rebuilds=0;v.rebuild=()=>{rebuilds++;throw Error('full rebuild during hosted drag');};
 assert.ok(handles.begin(pixel(descriptor.at),h));handles.update(pixel([descriptor.at[0]+1,descriptor.at[1],descriptor.at[2]]),{free:true});
 assert.ok(previews.length);assert.notDeepEqual(drawn(v,'b',id),before);assert.deepEqual(drawn(v,'c','w1'),other);
 await handles.finish();assert.equal(ops.length,1);assert.equal(rebuilds,0);results.push(ops[0]);
 }finally{abort.abort();v.dispose();}}
 assert.deepEqual(results[0],results[1]);
});
await test('non_room_selection_keeps_accent_tint',async()=>{
 const {view:v,controller:s}=await setup();try{
 s.select({kind:'opening',id:'o',building:'b',level:'L1'});
 const picked=[];v.scene.traverse(o=>{if((o.userData.pieceId==='o'||o.userData.snapRanges?.some(r=>r.pieceId==='o'&&r.buildingId==='b'))&&o.material&&!o.layers.isEnabled(31))picked.push(o);});
 assert.ok(picked.length);assert.ok(picked.some(o=>[].concat(o.material).some(m=>m.userData.selectionTint!==undefined)));
 }finally{v.dispose();}
});
await test('focus_survives_selection_view_levels_and_rebuild_with_cached_variants',async()=>{
 const {view:v,controller:s,plan}=await setup();try{
 s.focusRoom('r','b');await v.selectionReady;
 const objects=[];v.scene.traverse(o=>{if(o.isMesh&&[].concat(o.material).some(m=>m.userData.styledFade))objects.push([o,o.material]);});
 assert.ok(objects.length);let compiles=0;v.compileModelMaterials=()=>{compiles++;return null;};
 s.select({kind:'opening',id:'o',building:'b'});await v.selectionReady;
 for(const [o,m]of objects)assert.equal(o.material,m,'same focus keeps displayed material identity');
 v.setView('b:L1');await v.selectionReady;v.showLevels(['b:L1','c:L1']);await v.selectionReady;
 assert.equal(compiles,0,'view changes reuse warmed variants');
 await v.rebuild(structuredClone(plan));await v.selectionReady;
 assert.ok(objects.every(([o])=>[].concat(o.material).some(m=>m.userData.styledFade)));
 assert.equal(compiles,0,'reused buildings retain warm focus variants');
 }finally{v.dispose();}
});
await test('focus_scope_adoption_shared_geometry_and_range_gaps',async()=>{
 const {createSelectionFocus}=await import(file('static/twin/selection_focus.js'));
 const root=new T.Group(),site=new T.Group();root.add(site);
 const geometry=new T.BoxGeometry().toNonIndexed(),material=new T.MeshStandardMaterial();geometry.clearGroups();
 geometry.userData.snapRanges=[{start:3,count:3,buildingId:'b',pieceId:'r'}];
 const a=new T.Mesh(geometry,material),b=new T.Mesh(geometry,material),sheet=new T.Mesh(geometry.clone(),material);
 root.add(a,b,sheet);const line=new T.Line(new T.BufferGeometry().setFromPoints([new T.Vector3(),new T.Vector3(1,0,0)]),new T.LineBasicMaterial());site.add(line);
 let finish;const focus=createSelectionFocus({compile:()=>new Promise(r=>finish=r),render:()=>{}});
 const pieces=new Map([['b:r',[a,b]]]),room={id:'r',building:'b',allowed:['r']};
 const pending=focus.apply(root,room,0xff0000,0xff00ff,{pieces,site});
 const replacement=material.clone();a.material=replacement;b.material=replacement;finish();await pending;
 assert.ok([].concat(a.material).some(m=>m.userData.styledFade),'unowned gaps get a filler group');
 assert.equal(a.geometry.groups.reduce((n,g)=>n+g.count,0),geometry.attributes.position.count);
 assert.equal(sheet.material,material,'drawing sheet outside pieces stays untouched');assert.ok(line.material.userData.styledFade);
 focus.restore();assert.equal(a.material,replacement,'adopt rereads material after model warmup');assert.equal(b.material,replacement);
 assert.deepEqual(geometry.groups,[],'shared geometry restored once');focus.dispose();
});
await test('bake_registration_cannot_recapture_presentation_materials',async()=>{
 const {registerBakeSource,bakeAuthoredMaterial,withAuthoredMaterials,captureBakeMaterials}=await import(file('static/twin/bake/source.js'));
 assert.equal(typeof captureBakeMaterials,'function');
 const root=new T.Group(),mesh=new T.Mesh(new T.BoxGeometry(),new T.MeshStandardMaterial());root.add(mesh);
 captureBakeMaterials(root);const authored=mesh.material;
 registerBakeSource(root,()=>root);mesh.material=authored.clone();mesh.material.userData.styledFade=true;
 registerBakeSource(root,()=>root);assert.equal(bakeAuthoredMaterial(root,mesh),authored);
 withAuthoredMaterials(root,()=>assert.equal(mesh.material,authored));assert.notEqual(mesh.material,authored);
});

await test('yard_deform_settle_keeps_authored_receivers_and_light_layout_in_every_presentation',async()=>{
 const results=[];
 for(const presentation of ['plain','focus','focus-leave','faint','unlit']){
  const {view:v,controller:s,plan}=await setup(p=>{
   p.site={lot:[[-5,-5],[65,-5],[65,30],[-5,30]],
    hardscape:[{id:'pad',polygon:[[14,0],[24,0],[24,10],[14,10]],material:'concrete'}],
    planting:[{id:'tree',preset:'oak',at:[25,15],height:8,seed:1}],
    pool:{id:'pool',polygon:[[15,15],[23,15],[23,23],[15,23]],depth:4,coping:1,elevation:0}};
  },true,'low',true);try{
   if(presentation.startsWith('focus'))s.focusRoom('r','b');
   if(presentation==='faint')v.showLevels(['b:L1','c:L1'],{faint:['b:L1']});
   if(presentation==='unlit')v.setUnlit(true);
   await v.selectionReady;
   const next=structuredClone(plan);next.buildings[0].rooms[0].polygon=next.buildings[0].rooms[0].polygon.map(([x,y],i)=>[i===1?13:x,y]);next.site.hardscape[0].polygon[1][0]=25;
   const settled=await v.settle(next);assert.equal(settled.path,'deform');
   while(v.yardSettling)await new Promise(r=>setTimeout(r,1));
   if(presentation==='focus-leave')s.leaveRoom();
   const atlas=buildAtlas(v.scene.children.find(isBakeRoot),v.plan,{room:{density:1,page:256,gutter:2}});
   v.scene.traverse(o=>{if(o.isMesh&&Array.isArray(o.material))assert.ok(o.geometry.groups.length,'focus groups follow replaced receiver geometry');});
   const missing=atlas.room.charts.filter(c=>!materialParts(c).length);assert.equal(missing.length,0,presentation+' charts without receivers');
   const lights=[{device:'fixture-light',building:'b',level:'L1',room:'r',at:[4,4,6]}];
   const layout=bakeLayout(atlas,{room:{density:1,page:256,gutter:2}},lights);
   assert.ok(layout.entries['fixture-light']?.key,'compare an actual light freshness key');
   console.log('  receiver '+presentation+' charts='+atlas.room.charts.length+' missing='+missing.length+' light='+layout.entries['fixture-light'].key);
   results.push({key:atlas.key,charts:atlas.room.charts.length,entries:layout.entries});
  }finally{v.dispose();}
 }
 for(const result of results)assert.deepEqual(result,results[0]);
});


await test('editor_and_viewer_generation_matches_main_high_and_low_with_viewer_only_objects',async()=>{
 const {registerHooks}=await import('node:module');
 const baselineURL=file('static/twin/plain-selection-main-generator.js');
 registerHooks({resolve(spec,ctx,next){return spec==='baseline-generator'?{url:baselineURL,shortCircuit:true}:next(spec,ctx);},
  load(url,ctx,next){return url===baselineURL?{source:input.mainGenerator,format:'module',shortCircuit:true}:next(url,ctx);}});
 const {buildTwin}=await import(file('static/twin/twin_generator.js')),baseline=await import('baseline-generator');
 const plan={buildings:[building('b')],site:{},materials:{}};
 plan.buildings[0].lights.push({id:'viewer-lamp',at:[5,5],level:'L1',visible_in:['viewer']});
 plan.buildings[0].fixtures=[{id:'viewer-table',kind:'table',level:'L1',rect:[1,1,4,4],height:3,visible_in:['viewer']}];
 const count=model=>{let meshes=0,lights=0;model.root.traverse(o=>{meshes+=!!o.isMesh;lights+=!!o.isRectAreaLight;});
  return {meshes,lights,keys:[...model.buildings.values()].map(e=>e.key)};};
 for(const tier of ['high','low'])for(const editor of [true,false]){
  const options={showAnchors:editor,viewing:!editor},reference=baseline.buildTwin(structuredClone(plan),{materials:{}},tier,options);
  const current=buildTwin(structuredClone(plan),{materials:{}},tier,options);await Promise.all([reference.ready,current.ready]);
  assert.deepEqual(count(current),count(reference),tier+' '+(editor?'editor':'viewer'));
  const focus=createSelectionFocusForTest(current);await focus.apply(current.root,{building:'b',id:'r',allowed:['r'],walls:[]},0xff0000,0xff00ff,{pieces:current.pieces,site:current.groups.site});
  assert.deepEqual(count(current),count(reference),'focus adds no mesh, light or generation key');focus.dispose();
 }
});

finish();
"""

from test_twin_selection_js import DRIVER as SELECTION_DRIVER
CONTROLLERS = (SELECTION_DRIVER.split("await test(", 1)[0]
    + SELECTION_DRIVER[SELECTION_DRIVER.index('function makeHousehold()'):SELECTION_DRIVER.index("await test('real_household")]) + r"""
const {createDraw}=await import(file('static/twin/editor/draw.js'));
const {roomInQuestion}=await import(file('static/twin/editor/room_context.js'));
await test('real_selected_room_split_and_ceiling_device_placement_without_focus',async()=>{
 const ed=await mountEditor();const abort=new AbortController();try{
  const b=ed.plan.buildings.find(b=>b.id==='pool-house'),room=b.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7');
  ed.tools.chooseFloor(b.id+':L1');ed.tools.select({kind:'room',id:room.id,building:b.id});
  assert.equal(ed.tools.selection().room,null);
  for(const id of ['draw-note','draw-tools','draw-options','draw-cancel',...['draw-room','add-porch','draw-wall','split-room','add-door','add-window','add-anchor','add-stair','add-solar-zone','add-meter','add-electric-panel','add-charger','add-parking'].map(k=>'rail-'+k)]){
   if(!document.getElementById(id)){const node=document.createElement('button');node.id=id;document.body.append(node);}
  }
  window.promptInput=async()=>null;
  const operations=[],draw=createDraw({view:ed.view,tools:ed.tools,getPlan:()=>ed.plan,op:async operation=>{operations.push(operation);},gesture:f=>f(),canEdit:()=>true,signal:abort.signal,panel:{message:assert.fail}});
  document.getElementById('rail-split-room').click();await new Promise(r=>setTimeout(r,0));
  const click=async point=>{const p=ed.pixel([...point,0],b),event={pointerId:5,button:0,clientX:p[0],clientY:p[1]};draw.pointerDown(event);draw.pointerUp(event,false);await new Promise(r=>setTimeout(r,0));};
  ed.look([16,8,0],b,80);await click([16,0]);await click([16,17.333333333333332]);
  assert.equal(operations[0]?.op,'split_room');assert.equal(operations[0].room,room.id);draw.cancel();
  const library=createLibrary({view:ed.view,kit:input.kit,getPlan:()=>ed.plan,tools:ed.tools,op:async()=>{},canEdit:()=>true,signal:abort.signal});
  ed.tools.select({kind:'room',id:room.id,building:b.id});ed.look([16,8,8],b,80);
  const p=ed.pixel([16,8,b.levels[0].ceiling],b),event={pointerId:6,button:0,clientX:p[0],clientY:p[1]};
  const ceiling=library.ceilingAt(event);assert.equal(ceiling?.piece.id,room.id);
  ed.devices.arm({device_id:'test-device',name:'Test device'},'ceiling');
  assert.ok(ed.devices.pointerDown(event));assert.ok(ed.devices.pointerUp(event,false));await new Promise(r=>setTimeout(r,0));
  const placed=ed.ops.find(o=>o.op==='place_device');assert.equal(placed?.host.ceiling,room.id);assert.equal(placed.building,b.id);
  assert.equal(ed.tools.selection().room,null);
  const binding={host:{ceiling:room.id}};
  assert.equal(roomInQuestion(ed.plan,{kind:'anchor',building:b.id},{building:b,piece:binding}).room,room);
  const opening=b.openings.find(o=>{const hit=roomInQuestion(ed.plan,{building:b.id},{building:b,piece:{host:{opening:o.id,side:'in'}}});return hit?.room.id===room.id;});
  assert.ok(opening,'an opening-hosted device resolves its room without focus');
 }finally{abort.abort();ed.dispose();}
});

await test('level_focus_keeps_all_generated_level_descendants_including_attachments',async()=>{
 const ed=await mountEditor();try{
  const rows=Object.entries(ed.view.groups.levels);
  assert.ok(rows.length>1);
  for(const [key,group]of rows){
   const building=group.userData.buildingId,level=key.slice(building.length+1);
   ed.tools.focusRoom({kind:'level',id:level,building});await ed.view.selectionReady;
   group.traverse(o=>{if(o.material&&!o.layers.isEnabled(31))assert.ok([].concat(o.material).every(m=>!m.userData.styledFade),o.userData.kind+' under '+key+' stays in focus');});
   const ids=ed.view.levelFocusMembers(building,level);assert.ok(ids.length>1);
  }
 }finally{ed.dispose();}
});
await test('plain_room_selection_does_not_dim_real_device_markers',async()=>{
 const ed=await mountEditor();try{
  const b=ed.plan.buildings.find(b=>b.rooms?.length),room=b.rooms.find(r=>r.state!=='ghost');
  const other=ed.plan.buildings.find(c=>c.id!==b.id&&c.rooms?.length),otherRoom=other.rooms.find(r=>r.state!=='ghost');
  other.devices=[{id:'marker-anchor',device:'marker-device',host:{floor:otherRoom.id,u:.5,v:.5}}];
  ed.tools.haLink.state=()=>({available:true,devices:[{device_id:'marker-device',kind:'sensor'}],rooms:[],areas:[]});
  ed.devices.refresh();ed.tools.select({kind:'room',id:room.id,building:b.id});ed.devices.draw();
  const markers=ed.view.scene.getObjectByName('editor-device-markers');assert.equal(markers.children.length,1);assert.equal(markers.children[0].material.opacity,1);
  ed.tools.focusRoom({kind:'room',id:room.id,building:b.id});await ed.view.selectionReady;ed.devices.draw();assert.equal(markers.children[0].material.opacity,.2);
  ed.tools.select(null);ed.plan.site.yard_rooms=[{id:'yard-marker-room',polygon:[[180,180],[220,180],[220,220],[180,220]]}];
  ed.tools.select({kind:'yard_rooms',id:'yard-marker-room'});ed.devices.draw();assert.equal(markers.children[0].material.opacity,.2,'yard-room marker dimming keeps main behavior');
 }finally{ed.dispose();}
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'mainGenerator': subprocess.check_output(['git', 'show', 'main:chauffeur/static/twin/twin_generator.js'], cwd=ROOT, text=True, encoding='utf-8')})
    print(out)
    if code:
        sys.exit(code)
    from services.twin_model_bridge import assemble, flatten
    flat = flatten(assemble(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')))[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, out = run_node(CONTROLLERS, {'root': ROOT.as_posix(), 'flat': flat, 'kit': kit,
        'objectSchema': json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf-8'))}, timeout=180)
    print(out)
    sys.exit(code or 0)
