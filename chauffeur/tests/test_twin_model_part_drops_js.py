"""Task 6 runtime paths: real part geometry, editor drops, shelf and history."""
import json
import sys
from pathlib import Path

from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX as PRELUDE
from test_model_parts_pipeline_js import DRIVER as PIPELINE

ROOT = Path(__file__).resolve().parents[1]
# Reuse Task 4's four-material generator, including its missing-UV mesh.
MODEL = PIPELINE[PIPELINE.index('const source=new THREE.Group();'):PIPELINE.index('const bytes=')]
DRIVER = PRELUDE + r"""
const THREE=await import(three);
""" + MODEL + r"""
const {stampParts}=await import(file('static/twin/model_levels.js'));
const {rememberImport,modelRecord}=await import(file('static/twin/twin_library.js'));
const {createLibrary,scopeChoices}=await import(file('static/twin/editor/library.js'));
const {createHistory,CHANGED_SINCE}=await import(file('static/twin/editor/history.js'));
const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
window.chfBase='../';
window.location={href:'http://house.test/house/editor'};
const parts=stampParts(source),asset='import-task6',material={id:'oak',kind:'material',name:'Oak',thumbnail_url:'fixture.png'};
let record={id:asset,kind:'furniture',name:'Four parts',revision:1,parts,materials:{Glass:{material:'glass'}}};
const builtins=new Map(),builtinLoads=new Map(),builtinPatches=new Map(),builtinFailures=new Set(),builtinConflicts=new Set();let builtinBytes;
rememberImport(record);
const plan=input.plan,b=plan.buildings.find(b=>b.rooms.length),room=b.rooms[0];
b.items=[0,1].map(i=>({id:'copy-'+i,asset,host:{floor:room.id,u:.3+i*.3,v:.5}}));
b.openings.push({id:'parts-door',kind:'door',model:asset,wall:b.walls[0].id});
plan.site.furniture=[{id:'yard-copy',asset,at:[1,2]}];
plan.site.planting=[{id:'plant-copy',asset,at:[2,3]}];
window.twinObjectSchema=input.schema;
const panel=document.getElementById('library-panel'),grid=document.getElementById('library-entries');
panel.append(grid,document.getElementById('library-actions'),document.getElementById('library-search'));
const canvas=document.createElement('canvas');document.getElementById('editor-scene').append(canvas);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1400/1000,.01,100);
camera.position.set(0,.2,3);camera.lookAt(0,.2,0);camera.updateMatrixWorld(true);
// The rendered ranges, rather than a proxy's material name, identify the part.
source.traverse(o=>{if(o.isMesh)o.userData.snapRanges=[{start:0,count:o.geometry.index.count,
 kind:'item',pieceId:'copy-0',buildingId:b.id,partKey:o.material.userData.partKey}];});scene.add(source);
let picked={kind:'item',id:'copy-0',building:b.id,point:[0,.2,.2]},round=1,ops=[],patches=[],reverts=[],alerts=[],conflict=false,reloads=0,incomingRound=false;
window.showGlobalAlert=text=>alerts.push(text);
globalThis.fetch=async(url,options={})=>{
 url=typeof url==='string'?url:url.url;
 let result,status=200,body=options.body&&JSON.parse(options.body);
 const builtinId=url.match(/\/models\/(builtin-[^/?]+)$/)?.[1];
 if(builtinId){
  const current=builtins.get(builtinId);assert.ok(current);
  if(options.method==='PATCH'){
   builtinPatches.set(builtinId,(builtinPatches.get(builtinId)||0)+1);
   if(builtinFailures.has(builtinId)){status=500;result={detail:'Stamp failed'};}
   else if(builtinConflicts.delete(builtinId)){status=409;result={detail:'Fix changed'};builtins.set(builtinId,{...current,revision:current.revision+1,fix:{turn:90}});}
   else {assert.equal(body.revision,current.revision);result={...current,...body,revision:current.revision+1};builtins.set(builtinId,result);}
  }else result=current;
 }else if(/\/library\/builtin-[^/]+\/original.glb$/.test(url)){const id=url.match(/\/library\/([^/]+)\//)[1];builtinLoads.set(id,(builtinLoads.get(id)||0)+1);return new Response(builtinBytes);}
 else if(url.endsWith('/models/'+asset)){
  if(options.method==='PATCH'){
   patches.push(body);
   if(conflict||body.revision!==record.revision){status=409;result={detail:'Model changed in another tab.',record};}
   else {record={...record,...body,revision:record.revision+1};result=record;}
  }else result=record;
 }else if(url.endsWith('/revert')){reverts.push(body.round);result={round:++round};}
 else if(url.endsWith('/materials'))result={materials:[material]};
 else if(url.endsWith('/library'))result={items:[],imports:[{...record,thumbnail_url:'fixture.png'}],materials:[]};
 else if(url.endsWith('/imports'))result=[];
 else if(url.endsWith('/import-settings'))result={limit_mb:50};
 else if(url.endsWith('/materials/manifest'))result={};
 else throw Error('Unexpected request '+url);
 return new Response(JSON.stringify(result),{status});
};
const abort=new AbortController(),history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,
 refresh:async()=>{reloads++;},signal:abort.signal});
const view={scene,camera,renderer3:{domElement:canvas},controls:new EventTarget(),pick:()=>picked};
const library=createLibrary({view,kit:{},getPlan:()=>plan,tools:{selection:()=>({})},
 op:async o=>ops.push(o),canEdit:()=>true,signal:abort.signal,history,refreshModels:async()=>{reloads++;if(incomingRound){incomingRound=false;round+=10;}}});
const wait=async()=>{await new Promise(r=>setTimeout(r,25));};
const event={clientX:700,clientY:500};
async function drop(scope){
 await library.reveal('material',material.id);
 const tile=grid.querySelector('[data-material="oak"]');document.elementFromPoint=()=>canvas;
 await fire(tile,'pointerdown',{button:0,pointerId:1,clientX:10,clientY:10});
 await fire(document,'pointerup',{pointerId:1,...event});
 if(scope)await click(document.getElementById('material-chooser').querySelectorAll('button').find(n=>n.textContent===scope));
 await wait();
}
async function key(back=true){await fire(document,'keydown',{key:'z',ctrlKey:true,shiftKey:!back});await wait();}
await test('fresh_selection_loads_material_names_and_catalogue_refreshes_retained_rows',async()=>{
 const {createCards}=await import(file('static/twin/editor/cards.js'));
 const {readMaterialNames,readLibraryCatalog}=await import(file('static/twin/editor/material_catalog.js'));
 record={...record,materials:{Wood:{material:'oak'}}};rememberImport(record);
 let names=0;const cards=createCards({getPlan:()=>plan,getKit:()=>({materials:{oak:{color:'#abc123'}}}),getLabel:()=> 'Chair',
  canEdit:()=>true,op:async()=>{},edit:async()=>{},select(){},ask(){},library,
  loadMaterialNames:()=>{names++;return readMaterialNames();}});
 const card=document.getElementById('piece-card');cards.draw({pieceId:'copy-0',buildingId:b.id});await wait();
 const row=card.querySelector('[data-model-part="Wood"]');assert.ok(row);assert.equal(names,1);
 assert.match(textOf(row),/Oak, from the model/);assert.equal(row.querySelector('[data-slot-swatch]').style.backgroundColor,'#abc123');
 material.name='Household wood';await readLibraryCatalog();
 assert.equal(card.querySelector('[data-model-part="Wood"]'),row);assert.match(textOf(row),/Household wood, from the model/);
 cards.dispose();material.name='After dispose';await readLibraryCatalog();assert.doesNotMatch(textOf(row),/After dispose/);
 material.name='Oak';await readLibraryCatalog();record={...record,materials:{Glass:{material:'glass'}}};rememberImport(record);
});
await test('drop_offers_model_scopes',async()=>{
 const hit=library.surfaceAt(event);assert.equal(hit.kind,'model-part');assert.equal(hit.partKey,'Wood');assert.equal(hit.asset,asset);
 await drop();assert.deepEqual(document.getElementById('material-chooser').querySelectorAll('button').map(n=>n.textContent),['This copy','The model (all copies)','Cancel']);
 const wall=b.walls[0];assert.deepEqual(scopeChoices({kind:'wall',level:wall.level}),[['This wall face','face'],['This room','room'],['This floor','level'],['The whole building','building']]);
});
await test('picked_ranges_identify_duplicate_and_unnamed_parts',async()=>{
 for(let i=0;i<parts.length;i++){
  camera.position.set(i*.5,.2,3);camera.lookAt(i*.5,.2,0);
  assert.equal(library.surfaceAt(event).partKey,parts[i].key);
 }
 camera.position.set(0,.2,3);camera.lookAt(0,.2,0);
});
await test('real_wall_and_pool_water_keep_existing_drop_scopes',async()=>{
 const {mountTwin}=await import(file('static/twin/twin_view.js'));
 const {surfaceOperation}=await import(file('static/twin/editor/library.js'));
 const square=[[0,0],[12,0],[12,12],[0,12]];
 const p={materials:{},buildings:[{id:'wall-test',position:[0,0],base:0,levels:[{id:'L1',elevation:0,ceiling:8,outline:square}],
  walls:square.map((from,i,a)=>({id:'w'+i,level:'L1',from,to:a[(i+1)%4],height:8,thickness:.5,exterior:true,state:'settled'})),
  rooms:[{id:'room',level:'L1',polygon:square,state:'settled'}],openings:[],items:[],anchors:[],roof:{sections:[],flags:[]}}],
  site:{lot:[[-10,-10],[100,-10],[100,100],[-10,100]],pool:{id:'test-water',polygon:[[60,60],[70,60],[70,70],[60,70]],depth:4,coping:1}}};
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const v=await mountTwin(host,{plan:p,kit:{materials:{}},tier:'low',bake:false});
 const controller=new AbortController(),lib=createLibrary({view:v,kit:{},getPlan:()=>p,tools:{selection:()=>({})},op:async()=>{},canEdit:()=>true,signal:controller.signal});
 try{
  v.scene.updateMatrixWorld(true);
  const aim=(mesh,start=0)=>{
   const g=mesh.geometry,position=g.attributes.position;
   const vertices=[0,1,2].map(i=>mesh.localToWorld(new THREE.Vector3().fromBufferAttribute(position,g.index?g.index.getX(start+i):start+i)));
   const point=vertices.reduce((a,b)=>a.add(b),new THREE.Vector3()).multiplyScalar(1/3);
   const normal=new THREE.Triangle(...vertices).getNormal(new THREE.Vector3());
   v.camera.near=.01;v.camera.position.copy(point).addScaledVector(normal,.3);v.camera.lookAt(point);v.camera.updateProjectionMatrix();v.camera.updateMatrixWorld(true);
   const rect=v.renderer3.domElement.getBoundingClientRect();return {clientX:rect.left+rect.width/2,clientY:rect.top+rect.height/2};
  };
  let wallMesh,wallRange,water,waterRange;
  v.scene.traverse(o=>{
   if(!o.isMesh)return;
   const range=(o.userData.snapRanges||o.geometry.userData.snapRanges||[]).find(r=>r.kind==='wall'&&!r.partKey);
   if(range&&!wallMesh){wallMesh=o;wallRange=range;}
   const wr=(o.userData.snapRanges||o.geometry.userData.snapRanges||[]).find(r=>r.kind==='pool'&&r.part==='water');
   if(wr){water=o;waterRange=wr;}
   else if(o.userData.kind==='pool'&&o.userData.part==='water'){water=o;waterRange={start:0};}
  });
  assert.ok(wallMesh,'generated non-model wall');assert.ok(water,'generated pool-water mesh');
  const wall=lib.surfaceAt(aim(wallMesh,wallRange.start));assert.equal(wall.kind,'wall');
  assert.deepEqual(scopeChoices(wall),[['This wall face','face'],['This room','room'],['This floor','level'],['The whole building','building']]);
  const pool=lib.surfaceAt(aim(water,waterRange.start));assert.equal(pool.kind,'pool');assert.equal(pool.role,'water');
  assert.deepEqual(pool.target,{pool:'test-water',part:'water'});
  assert.deepEqual(surfaceOperation(pool,'face',material),{op:'update_site_shape',list:'pool',id:'test-water',materials:{water:{id:'oak'}}});
 }finally{controller.abort();v.dispose();}
});
await test('this_copy_sets_model_materials',async()=>{
 b.items[0].model_materials={Glass:{material:'original'}};
 await drop('This copy');assert.deepEqual(ops.at(-1),{op:'set_object',building:b.id,id:'copy-0',properties:{model_materials:{Glass:{material:'original'},Wood:{material:'oak'}}}});
 assert.equal(b.items[1].model_materials,undefined);
});
await test('opening_and_yard_drops_keep_their_copy_owner',async()=>{
 for(const [kind,id,bid] of [['opening','parts-door',b.id],['furniture','yard-copy',null],['planting','plant-copy',null]]){
  source.traverse(o=>{if(o.isMesh)Object.assign(o.userData.snapRanges[0],{kind,pieceId:id,buildingId:bid});});
  // Yard models have no selection proxy; the view can pick the floor behind.
  picked=bid?{kind,id,building:bid,point:[0,.2,.2]}:{kind:'room',id:room.id,building:b.id,point:[0,.2,-2]};
  const hit=library.surfaceAt(event);assert.equal(hit.kind,'model-part');assert.equal(hit.pieceId,id);
  await drop('This copy');const operation=ops.at(-1);assert.equal(operation.op,'set_object');
  assert.equal(operation.properties.model_materials.Wood.material,'oak');
  if(bid)assert.equal(operation.id,id);else {assert.equal(operation.list,kind);assert.equal(operation.index,0);}
 }
 source.traverse(o=>{if(o.isMesh)Object.assign(o.userData.snapRanges[0],{kind:'item',pieceId:'copy-0',buildingId:b.id});});
 picked={kind:'item',id:'copy-0',building:b.id,point:[0,.2,.2]};
 assert.notEqual(library.surfaceAt(event,{modelParts:false})?.kind,'model-part','model-file placement retains the underlying surface');
});
await test('selected_cards_refresh_model_defaults_without_a_house_round',async()=>{
 const {createCards}=await import(file('static/twin/editor/cards.js'));
 const cards=createCards({getPlan:()=>plan,getKit:()=>({}),getLabel:()=> 'Four-part copy',
  canEdit:()=>true,op:async o=>ops.push(o),edit:async()=>{},select(){},ask(){},library});
 const card=document.getElementById('piece-card'),selection={pieceId:'copy-0',buildingId:b.id};
 cards.draw(selection);await wait();assert.equal(card.querySelectorAll('[data-model-part]').length,4);
 const row=card.querySelector('[data-model-part="Wood~2"]');
 record={...record,revision:record.revision+1,materials:{'Wood~2':{material:'oak'}}};rememberImport(record);
 cards.draw(selection);await wait();assert.equal(card.querySelector('[data-model-part="Wood~2"]'),row,'same card retains its row');
 assert.ok(textOf(row).includes('from the model'));
 cards.draw({pieceId:'parts-door',buildingId:b.id});await wait();assert.equal(card.querySelectorAll('[data-model-part]').length,4);
 cards.dispose();card.remove();
});
await test('model_scope_undo_redo',async()=>{
 history.clear();await history.perform(async()=>{round++;});const roundBeforeModel=round;
 await drop('The model (all copies)');assert.deepEqual(patches.at(-1).materials.Wood,{material:'oak'});assert.ok(reloads);
 await history.perform(async()=>{round++;});
 await key();assert.equal(reverts.at(-1),roundBeforeModel);
 await key();assert.equal(record.materials.Wood,undefined);assert.equal((await modelRecord(asset)).revision,record.revision);
 await key();assert.equal(reverts.at(-1),1,'round before the model remains connected through its fresh revert round');
 await key(false);await key(false);assert.deepEqual(record.materials.Wood,{material:'oak'});
 await key(false);assert.equal(document.getElementById('rail-redo').disabled,true);assert.deepEqual(alerts,[]);
});
await test('undo_conflict_stops',async()=>{
 history.clear();history.record({kind:'model-record',asset,revision:record.revision,before:{materials:{}},after:{materials:record.materials}});
 conflict=true;const count=patches.length;await key();assert.equal(alerts.length,1);assert.equal(patches.length,count+1);
 assert.equal(document.getElementById('rail-undo').disabled,false);assert.equal(document.getElementById('rail-redo').disabled,true);
 conflict=false;await key();assert.equal(record.materials.Wood,undefined);assert.equal(document.getElementById('rail-undo').disabled,true);
});
await test('stale_revision_refuses_repeated_undo_and_redo_after_cache_refresh',async()=>{
 for(const back of [true,false]){
  history.clear();await drop('The model (all copies)');if(!back)await key();
  const expected=record.revision,external={Glass:{material:'external'},Wood:{material:'external'}};
  record={...record,revision:expected+1,materials:external};rememberImport(record);
  const count=patches.length,shown=alerts.length;
  for(let i=1;i<=2;i++){
   await key(back);assert.equal(patches.at(-1).revision,expected);assert.deepEqual(record.materials,external);
   assert.equal(patches.length,count+i);assert.equal(alerts.length,shown+i,'one alert per conflict');
   assert.equal(document.getElementById('rail-undo').disabled,!back);assert.equal(document.getElementById('rail-redo').disabled,back);
  }
 }
});
await test('consecutive_model_edits_undo_redo_across_round_and_other_asset_steps',async()=>{
 history.clear();const before=structuredClone(record.materials);
 await drop('The model (all copies)');const first=structuredClone(record.materials);
 await history.perform(async()=>{round++;});
 const other='builtin-history-task6';builtins.set(other,{id:other,revision:2,parts,materials:{Wood:{material:'oak'}}});
 history.record({kind:'model-record',asset:other,revision:2,before:{materials:{}},after:{materials:{Wood:{material:'oak'}}}});
 record={...record,revision:record.revision+1,materials:{...record.materials,Glass:{material:'glass'}}};rememberImport(record);
 // A second local model write, as a separate material drop would record it.
 history.record({kind:'model-record',asset,revision:record.revision,before:{materials:first},after:{materials:record.materials}});
 await key();await key();assert.deepEqual(builtins.get(other).materials,{});
 await key();await key();assert.deepEqual(record.materials,before);
 await key(false);await key(false);await key(false);await key(false);assert.equal(record.materials.Glass.material,'glass');
 assert.equal(builtins.get(other).materials.Wood.material,'oak');
 record={...record,materials:{}};rememberImport(record);
});
await test('new_local_edit_after_external_edit_does_not_reconnect_older_history',async()=>{
 history.clear();await drop('The model (all copies)');
 record={...record,revision:record.revision+1,materials:{Glass:{material:'external'}}};rememberImport(record);
 await drop('The model (all copies)');await key();
 assert.deepEqual(record.materials,{Glass:{material:'external'}});
 const shown=alerts.length;await key();
 assert.equal(alerts.length,shown+1);assert.deepEqual(record.materials,{Glass:{material:'external'}});
 assert.equal(document.getElementById('rail-undo').disabled,false);assert.equal(document.getElementById('rail-redo').disabled,false);
 record={...record,materials:{}};rememberImport(record);
});
await test('incoming_house_round_during_model_edit_is_never_recorded_as_ours',async()=>{
 history.clear();const count=reverts.length;
 incomingRound=true;await drop('The model (all copies)');
 await key();assert.equal(reverts.length,count,'Undo restores only the model, never the polled house round');
 assert.equal(record.materials.Wood,undefined);assert.equal(document.getElementById('rail-undo').disabled,true);
});
await test('round_guard_through_model_step',async()=>{
 history.clear();await history.perform(async()=>{round++;});history.record({kind:'model-record',asset,revision:record.revision,before:{materials:{}},after:{materials:{}}});
 round+=10;await key();const count=reverts.length;await key();assert.equal(reverts.length,count);assert.equal(alerts.at(-1),CHANGED_SINCE);
});
await test('parts_rows_on_card',async()=>{
 record={...record,revision:record.revision+1,materials:{Wood:{material:'oak'}}};rememberImport(record);
 b.items[0].model_materials={Glass:{material:'original'}};
 for(const r of [{kind:'item',piece:b.items[0],building:b},{kind:'opening',piece:b.openings.at(-1),building:b}]){
  const host=document.createElement('div');document.body.append(host);const slots=[];
  drawObjectShelf(host,r,{canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async o=>ops.push(o),report:e=>{throw e;},library,ownSlot:s=>slots.push(s)});
  await wait();const section=host.querySelector('[aria-label="Parts"]');assert.ok(section);
  assert.equal(section.querySelectorAll('[data-library-slot]').length,4);
  assert.deepEqual(section.querySelectorAll('[data-slot-label]').map(n=>n.textContent),['Wood','unnamed','Wood~2','Glass']);
  assert.ok(textOf(section).includes('from the model'));
  if(r.kind==='item'){
   assert.ok(textOf(section).includes('original (this copy)'));
   const glass=section.querySelector('[data-library-slot="Glass"]');await click(glass.querySelector('[data-slot-clear]'));
   assert.equal(ops.at(-1).properties.model_materials.Glass,undefined);
   library.select(material);const wood=section.querySelector('[data-library-slot="Wood"]');await click(wood.querySelector('[data-slot-use]'));
   assert.deepEqual(ops.at(-1).properties.model_materials.Wood,{material:'oak'});
   await click(wood.querySelector('[data-slot-reset]'));assert.deepEqual(ops.at(-1).properties.model_materials.Wood,{material:'original'});
   assert.equal(wood.querySelector('[data-slot-reset]').disabled,true,'already original');
   record={...record,revision:record.revision+1,materials:{unnamed:{material:'oak'}}};rememberImport(record);
   slots.forEach(s=>s.refresh());await wait();assert.ok(textOf(section.querySelector('[data-model-part="unnamed"]')).includes('from the model'));
   assert.equal(section.querySelector('[data-model-part="Wood~2"] [data-slot-reset]').disabled,true,'original with no override');
  }
  slots.forEach(s=>s.dispose());host.remove();
 }
});
await test('legacy_parts_appear_after_background_stamp',async()=>{
 const emptyId='import-legacy-parts';rememberImport({id:emptyId,revision:1,parts:[]});
 const r={kind:'item',piece:{id:'legacy',asset:emptyId,at:[0,0]},building:b};
 const host=document.createElement('div');document.body.append(host);const slots=[];
 drawObjectShelf(host,r,{canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async()=>{},report:e=>{throw e;},library,ownSlot:s=>slots.push(s)});
 await wait();assert.equal(host.querySelector('[aria-label="Parts"]'),null);
 rememberImport({id:emptyId,revision:2,parts,parts_version:1});slots.forEach(s=>s.refresh());await wait();
 assert.equal(host.querySelectorAll('[data-model-part]').length,4);
 slots.forEach(s=>s.dispose());host.remove();
});
await test('first_use_builtins_stamp_before_rows_or_copy_drops',async()=>{
 globalThis.ProgressEvent=class{constructor(type,values){Object.assign(this,values);}};
 globalThis.FileReader=class{readAsArrayBuffer(blob){blob.arrayBuffer().then(value=>{this.result=value;this.onloadend?.();});}};
 const {GLTFExporter}=await import(file('static/vendor/three-r187/addons/exporters/GLTFExporter.js'));
 builtinBytes=await new GLTFExporter().parseAsync(source.clone(true),{binary:true});
 const until=async predicate=>{for(let i=0;i<100&&!predicate();i++)await wait();assert.ok(predicate(),'built-in preparation finishes');};
 for(const id of ['builtin-row-task6','builtin-drop-task6'])builtins.set(id,{id,revision:1,kind:'model',model:'original.glb',files:{'original.glb':true},parts:[]});
 const host=document.createElement('div');document.body.append(host);const slots=[];
 const r={kind:'item',piece:{id:'builtin-copy',asset:'builtin-row-task6',at:[0,0]},building:b};
 drawObjectShelf(host,r,{canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async()=>{},report:e=>{throw e;},library,ownSlot:s=>slots.push(s)});
 await until(()=>host.querySelectorAll('[data-model-part]').length===4);
 assert.equal(builtins.get(r.piece.asset).parts_version,1);slots.forEach(s=>s.dispose());host.remove();
 const oldAsset=b.items[0].asset;b.items[0].asset='builtin-drop-task6';
 try{
  const count=ops.length;await drop('This copy');await until(()=>ops.length>count);
  assert.equal(builtins.get(b.items[0].asset).parts_version,1,'drop prepares the server contract without opening Library or Properties first');
  assert.equal(builtins.get(b.items[0].asset).parts.length,4);
 }finally{b.items[0].asset=oldAsset;}
});
await test('builtin_stamp_concurrency_retry_and_failure_cooldown',async()=>{
 const {prepareModelParts}=await import(file('static/twin/editor/model_records.js'));
 for(const id of ['builtin-concurrent','builtin-conflict','builtin-failure'])builtins.set(id,{id,revision:1,kind:'model',model:'original.glb',files:{'original.glb':true},parts:[]});
 await Promise.all([prepareModelParts('builtin-concurrent'),prepareModelParts('builtin-concurrent')]);
 assert.equal(builtinLoads.get('builtin-concurrent'),1);assert.equal(builtinPatches.get('builtin-concurrent'),1);
 builtinConflicts.add('builtin-conflict');const fixed=await prepareModelParts('builtin-conflict');
 assert.equal(fixed.parts_version,1);assert.deepEqual(fixed.fix,{turn:90});assert.equal(builtinPatches.get('builtin-conflict'),2);assert.equal(builtinLoads.get('builtin-conflict'),1);
 builtinFailures.add('builtin-failure');
 const host=document.createElement('div'),slots=[],errors=[];document.body.append(host);
 const r={kind:'item',piece:{id:'failed-copy',asset:'builtin-failure',at:[0,0]},building:b};
 drawObjectShelf(host,r,{canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async()=>{},report:e=>errors.push(e),library,ownSlot:s=>slots.push(s)});
 await wait();for(let i=0;i<5;i++){slots.forEach(s=>s.refresh());await wait();}
 assert.equal(errors.length,1);assert.equal(builtinLoads.get('builtin-failure'),1);assert.equal(builtinPatches.get('builtin-failure'),1);
 assert.ok(host.querySelectorAll('input').length,'other Properties fields remain usable');
 // Once the cooldown expires, a successful refresh fills this retained card.
 const now=Date.now;Date.now=()=>now()+30001;builtinFailures.delete('builtin-failure');
 try{slots.forEach(s=>s.refresh());for(let i=0;i<40&&!host.querySelectorAll('[data-model-part]').length;i++)await wait();assert.equal(host.querySelectorAll('[data-model-part]').length,4);
  assert.equal(builtinLoads.get('builtin-failure'),2);assert.equal(builtinPatches.get('builtin-failure'),2);assert.equal(errors.length,1);
 }finally{Date.now=now;slots.forEach(s=>s.dispose());host.remove();}
});
await test('failed_record_read_alerts_once_and_recovers_on_retained_card',async()=>{
 const host=document.createElement('div'),slots=[],errors=[];document.body.append(host);
 const r={kind:'item',piece:{id:'failed-read',asset:'import-unavailable',at:[0,0]},building:b};
 const originalFetch=globalThis.fetch;let reads=0;
 globalThis.fetch=(url,options)=>String(url).endsWith('/models/import-unavailable')?(reads++,Promise.resolve(new Response('',{status:503}))):originalFetch(url,options);
 try{
  drawObjectShelf(host,r,{canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async()=>{},report:e=>errors.push(e),library,ownSlot:s=>slots.push(s)});
  await wait();for(let i=0;i<5;i++){slots.forEach(s=>s.refresh());await wait();}
  assert.equal(errors.length,1);assert.equal(reads,1);
  rememberImport({id:r.piece.asset,revision:1,parts,parts_version:1});slots.forEach(s=>s.refresh());await wait();
  assert.equal(host.querySelectorAll('[data-model-part]').length,4);
 }finally{globalThis.fetch=originalFetch;slots.forEach(s=>s.dispose());host.remove();}
});
await test('history_cap_and_redo_invalidation',async()=>{
 history.clear();for(let i=0;i<55;i++){record={...record,revision:record.revision+1};history.record({kind:'model-record',asset,revision:record.revision,before:{materials:{}},after:{materials:{}}});}rememberImport(record);
 const count=patches.length;for(let i=0;i<51;i++)await key();assert.equal(patches.length-count,50);
 history.record({kind:'model-record',asset,revision:record.revision,before:{materials:{}},after:{materials:{}}});assert.equal(document.getElementById('rail-redo').disabled,true);
});
await test('edit_in_library_link',async()=>{
 library.select({...record,kind:'furniture'});const link=document.getElementById('library-actions').querySelector('a');
 assert.equal(link.href,'../house/library?model='+asset);assert.equal(link.target,'_blank');assert.equal(link.rel,'noopener');
});
abort.abort();finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': flatten(assemble(fixture)[0]),
        'schema': json.loads((ROOT / 'static/twin/object_schema.json').read_text())})
    print(output)
    sys.exit(code)
