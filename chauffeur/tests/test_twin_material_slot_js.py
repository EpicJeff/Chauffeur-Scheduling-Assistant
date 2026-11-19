"""Shared material-slot DOM and the real porch card: one change, one op."""
import json
import os
import sys
import tempfile
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REGRESSIONS = PRELUDE + r"""
const slotListeners=new Set();let selectedMaterial=null;
const library={selected:()=>selectedMaterial,onSelect:fn=>{slotListeners.add(fn);return()=>slotListeners.delete(fn);},reveal:async()=>{}};
async function useMaterial(slot,id){selectedMaterial={kind:'material',id,name:id};for(const fn of slotListeners)fn();await click(slot.querySelector('[data-slot-use]'));}

const {materialSlot}=await import(file('static/twin/editor/material_slot.js'));
const {readLibraryCatalog}=await import(file('static/twin/editor/material_catalog.js'));
const entry={id:'material-household',name:'Household stone',color:'#789abc',thumbnail_url:'/ingress/test/stone.png'};
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
const make=value=>{const calls=[],node=materialSlot({library,label:'Surface',value,defaultLabel:'Stone',
 loadMaterials:async()=>[entry],onChange:async v=>calls.push(v)});return {node,calls};};
await test('pick_saves_id_only',async()=>{
 const {node,calls}=make(null);
 assert.equal(node.dataset.librarySlot,'Surface');
 await useMaterial(node,entry.id);assert.deepEqual(calls,[{id:entry.id}]);
});
await test('default_label_and_current_name_survive_the_shared_row_adapter',async()=>{
 const node=materialSlot({library,label:'Slab',defaultLabel:'Concrete',loadMaterials:async()=>[entry],onChange:async()=>{}});
 assert.equal(textOf(node.querySelector('[data-slot-name]')),'House default: Concrete');
 await useMaterial(node,entry.id);
 assert.equal(textOf(node.querySelector('[data-slot-name]')),entry.name);
 await click(node.querySelector('[data-slot-clear]'));
 assert.equal(textOf(node.querySelector('[data-slot-name]')),'House default: Concrete');
});
await test('override_then_clear',async()=>{
 const {node,calls}=make({id:entry.id});
 const tint=node.querySelector('input[type="color"]');assert.equal(textOf(tint.parentElement),'Override tint');
 tint.value='#123456';await fire(tint,'change');assert.deepEqual(calls,[{id:entry.id,color:'#123456'}]);
 await click(byText(node,'Clear override'));
 assert.deepEqual(calls,[{id:entry.id,color:'#123456'},{id:entry.id}]);
 assert.equal(byText(node,'Clear override').hidden,true);
 await click(byText(node,'Clear'));assert.equal(calls.at(-1),null);
});
await test('legacy_color_shows_clear_override',async()=>{
 const {node,calls}=make({id:entry.id,color:'#123456'});
 assert.equal(node.querySelector('input[type="color"]').value,'#123456');
 const clear=byText(node,'Clear override');assert.ok(clear);await click(clear);
 assert.deepEqual(calls,[{id:entry.id}]);
});
await test('catalogue_uses_household_rows_and_passes_thumbnail',async()=>{
 const urls=[];window.chfBase='/ingress/test/';
 globalThis.fetch=async url=>{urls.push(url);return new Response(JSON.stringify(url.endsWith('/materials')
  ?{revision:7,materials:[entry]}:{materials:[{id:'duplicate-preset',color:'#ffffff'}],items:[{id:'chair'}],imports:[{id:'import-chair'}],import_limit_mb:50}));};
 const catalog=await readLibraryCatalog();
 assert.deepEqual(urls.sort(),['/ingress/test/api/house/editor/library','/ingress/test/api/house/materials']);
 assert.deepEqual(catalog.materials,[entry]);assert.equal(catalog.revision,7);
 assert.deepEqual(catalog.items,[{id:'chair'}]);assert.deepEqual(catalog.imports,[{id:'import-chair'}]);assert.equal(catalog.import_limit_mb,50);
 const {node}=make({id:entry.id});await new Promise(resolve=>setTimeout(resolve,0));
 assert.equal(node.querySelector('[data-slot-swatch] img').src,entry.thumbnail_url);
 assert.equal(textOf(node.querySelector('[data-slot-name]')),entry.name,'initial metadata loads without opening a chooser');
});
await test('quick_picks_do_not_change_assignment_identity',async()=>{
 const calls=[],node=materialSlot({library,label:'Surface',defaultLabel:'Stone',
  quickPicks:[{id:entry.id,color:'#ffffff'},{id:entry.id,color:'#000000'},{id:'not-in-catalogue'}],
  loadMaterials:async()=>[entry],onChange:async v=>calls.push(v)});
 assert.equal(node.querySelectorAll('[data-material]').length,0,'all assignment uses the shared row');
 await useMaterial(node,entry.id);assert.deepEqual(calls,[{id:entry.id}]);
});
await test('slot_owner_disposal_unsubscribes_and_prevents_stale_apply',async()=>{
 let owned;const calls=[],node=materialSlot({library,label:'Surface',value:{id:entry.id},ownSlot:row=>owned=row,
  loadMaterials:async()=>[entry],onChange:async value=>calls.push(value)});
 assert.ok(owned);const before=slotListeners.size;owned.dispose();assert.equal(slotListeners.size,before-1);
 await useMaterial(node,entry.id);assert.deepEqual(calls,[]);
});
await test('dynamic_readonly_blocks_use_clear_tint_and_drop',async()=>{
 let locked=false;const sent=[],node=materialSlot({library,label:'Surface',value:{id:entry.id},readOnly:()=>locked,
  loadMaterials:async()=>[entry],onChange:async value=>sent.push(value)});
 locked=true;await useMaterial(node,'another-material');await click(node.querySelector('[data-slot-clear]'));
 const tint=node.querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');
 await fire(node,'chf-library-slot-drag',{detail:{phase:'drop',entry:{kind:'material',id:'another-material'}}});
 assert.deepEqual(sent,[]);
});
await test('every_porch_foundation_part_preserves_apply_tint_clear_payloads',async()=>{
 const {porchFoundationShelf}=await import(file('static/twin/editor/porch_foundation_shelf.js'));
 const {porchFoundation}=await import(file('static/twin/twin_porch_foundation.js'));
 for(const [part,label,type]of [['posts','Posts and beam','posts'],['skirt','Skirt','enclosed'],['solid','Solid base','solid']]){
  const room={id:'porch',level:'L',polygon:[[0,0],[8,0],[8,8],[0,8]],foundation:{type}},building={id:'b',levels:[{id:'L',elevation:2}],rooms:[room]};
  const plan={buildings:[building],site:{terraces:[]}},host=document.createElement('div'),sent=[],owned=[];
  porchFoundationShelf(host,room,building,{library,ownSlot:row=>owned.push(row),getPlan:()=>plan,canEdit:()=>true,queue:work=>work(),
   report:e=>{throw e;},onSaved(){},op:async op=>{sent.push(structuredClone(op));room.foundation=op.foundation;}});
  const slot=host.querySelector(`[data-library-slot="${label}"]`);
  for(const material of [{id:entry.id},{id:entry.id,color:'#123456'},{id:entry.id},null]){
   const foundation=porchFoundation(room.foundation);foundation.materials[part]=material;delete foundation.material;
   const n=sent.length;
   if(!material)await click(slot.querySelector('[data-slot-clear]'));
   else if(material.color){const tint=slot.querySelector('input[type="color"]');tint.value=material.color;await fire(tint,'change');}
   else if(n)await click(byText(slot,'Clear override'));else await useMaterial(slot,entry.id);
   assert.equal(sent.length,n+1);assert.deepEqual(sent.at(-1),{op:'set_porch_foundation',building:'b',id:'porch',foundation},part+' old payload');
  }
  for(const row of owned)row.dispose();
 }
});
await test('every_pad_edge_slot_preserves_payload_and_disposes_on_replace_close_abort',async()=>{
 const THREE=await import(three),{createTerrainTools}=await import(file('static/twin/editor/terrain_tools.js'));
 const shell=document.createElement('div');shell.className='editor-shell';document.body.append(shell);
 const canvas=document.createElement('canvas');shell.append(canvas);
 const controls=new THREE.EventDispatcher();controls.enabled=true;
 const view={renderer3:{domElement:canvas},scene:new THREE.Group(),camera:new THREE.PerspectiveCamera(50,1,.1,1000),
  controls,state:{view:'ext'},groups:{},setView(){},render(){}};
 view.camera.position.set(4,20,4);view.camera.lookAt(0,0,0);view.camera.updateMatrixWorld();
 const pad={id:'pad',height:1,polygon:[[0,0],[12,0],[12,8],[0,8]],edges:[
  {edge:'sharp',wall:{material:'block',thickness_in:8,cap:{thickness_in:2},rail:{style:'panel'}}},
  {edge:'sharp',stair:{riser_in:7,tread_in:11,rail:{style:'pickets'}}},
  {edge:'sharp',stair:{treads:false,rail:{style:'cable'}}},{edge:'slope'}]};
 const plan={buildings:[],site:{terraces:[pad]}},sent=[],abort=new AbortController();
 const terrain=createTerrainTools({view,library,getPlan:()=>plan,tools:{setTool(){},select(){}},canEdit:()=>true,
  signal:abort.signal,op:async op=>{sent.push(structuredClone(op));Object.assign(pad,op);}});
 const before=slotListeners.size;terrain.choose('terraces','pad');
 const host=document.getElementById('terrain-card'),labels=host.querySelectorAll('[data-library-slot]').map(n=>n.dataset.librarySlot);
 assert.deepEqual(labels,['Edge 1 Wall face','Edge 1 Cap','Edge 1 Railing material','Edge 2 Risers','Edge 2 Treads material','Edge 2 Railing material','Edge 3 Risers','Edge 3 Railing material']);
 assert.equal(slotListeners.size,before+labels.length);
 for(const label of labels){
  const i=Number(label[5])-1,kind=pad.edges[i].wall?'wall':'stair',key=label.includes('Railing')?'rail':label.includes('Wall face')?'face':label.includes('Cap')?'cap':label.includes('Risers')?'riser':'tread';
  for(const material of [{id:entry.id},null]){
   const edges=structuredClone(pad.edges),owner=key==='rail'?edges[i][kind].rail:edges[i][kind];
   owner.materials={...owner.materials,[key]:material};if(!material)delete owner.materials[key];if(!Object.keys(owner.materials).length)delete owner.materials;
   const slot=host.querySelector(`[data-library-slot="${label}"]`),n=sent.length;
   if(material)await useMaterial(slot,entry.id);else await click(slot.querySelector('[data-slot-clear]'));
   assert.equal(sent.length,n+1);assert.deepEqual(sent.at(-1),{op:'update_pad',id:'pad',edges},label+' old payload');
   assert.equal(slotListeners.size,before+labels.length,'replacement disposes old rows');
  }
 }
 terrain.cancel();assert.equal(slotListeners.size,before,'close disposes rows');
 terrain.choose('terraces','pad');assert.equal(slotListeners.size,before+labels.length);
 abort.abort();assert.equal(slotListeners.size,before,'abort disposes rows');
});
finish();
"""
DRIVER = PRELUDE + r"""
const slotListeners=new Set();let selectedMaterial=null;
const library={selected:()=>selectedMaterial,onSelect:fn=>{slotListeners.add(fn);return()=>slotListeners.delete(fn);},reveal:async()=>{}};
async function useMaterial(slot,id){selectedMaterial={kind:'material',id,name:id};for(const fn of slotListeners)fn();await click(slot.querySelector('[data-slot-use]'));}

const {materialSlot}=await import(file('static/twin/editor/material_slot.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {porchFoundation}=await import(file('static/twin/twin_porch_foundation.js'));
const entries=[{id:'painted_trim',name:'Painted trim',color:'#f4f3ef'},{id:'wood_planks',name:'Wood planks',color:'#998877'},{id:'lattice',name:'Lattice',color:'#f4f3ef'}];
let fetches=0;globalThis.fetch=async url=>{assert.ok(url.endsWith('/api/house/editor/library')||url.endsWith('/api/house/materials'));fetches++;return {ok:true,text:async()=>JSON.stringify({materials:entries,items:[]})};};
const calls=[],errors=[];let locked=false;
const node=materialSlot({library,label:'Posts',value:null,defaultLabel:'Trim',defaultColor:'#ffffff',quickPicks:[entries[1]],
 readOnly:()=>locked,onChange:async v=>calls.push(v),report:e=>errors.push(e.message)});document.body.append(node);
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
assert.ok(textOf(node).includes('House default: Trim'));
await new Promise(resolve=>setTimeout(resolve,0));assert.equal(fetches,2);assert.equal(calls.length,0,'metadata load is never a history step');
assert.equal(node.dataset.librarySlot,'Posts');
await useMaterial(node,'wood_planks');assert.deepEqual(calls,[{id:'wood_planks'}]);
assert.ok(textOf(node).includes('Wood planks'));
await useMaterial(node,'wood_planks');assert.equal(calls.length,1,'reselect is no op');
// Reselect remains a no-op and still permits clearing/tinting.
const tint=node.querySelector('input[type="color"]');tint.value='#abcdef';await fire(tint,'change');
assert.deepEqual(calls.at(-1),{id:'wood_planks',color:'#abcdef'});assert.equal(calls.length,2);
await click(byText(node,'Clear'));assert.equal(calls.at(-1),null);assert.equal(calls.length,3);
assert.ok(textOf(node).includes('House default: Trim'));
locked=true;assert.equal(node.querySelector('[role="group"]'),null);assert.equal(calls.length,3);
const readonly=materialSlot({library,label:'Solid',value:{id:'wood_planks'},defaultLabel:'Stone',readOnly:true,onChange:()=>{throw Error('read-only wrote');}});
assert.equal(readonly.querySelectorAll('button,input').length,0);assert.ok(textOf(readonly).includes('Wood planks'));
const idOnly=materialSlot({library,label:'Solid',value:{id:'base'},defaultLabel:'Stone',kit:input.kit,readOnly:true});
assert.equal(idOnly.querySelector('[data-slot-swatch]').style.backgroundColor,input.kit.materials.base.color);
assert.ok(textOf(idOnly).includes('Stacked stone wall'));
// A failed save is visible, keeps the chosen/default value, and may be retried.
const failed=materialSlot({library,label:'Skirt',defaultLabel:'Trim',onChange:async()=>{throw Error('save failed');},report:e=>errors.push(e.message)});document.body.append(failed);
await useMaterial(failed,'wood_planks');assert.ok(textOf(failed).includes('House default: Trim'));assert.deepEqual(errors,['save failed']);
console.log('Passed: shared slot catalogue, swatch/name, choose, quick picks, tint, default, duplicate suppression, read-only and error');
// Yard features (user, 2026-11-13): each part's slot sits in the shared yard shape card.
{
  const {drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
  const square=[[0,0],[6,0],[6,4],[0,4]];
  for(const [kind,piece,parts] of [
    ['fence',{id:'f',polyline:[[0,0],[4,0]],height:6},['Boards','Posts','Rails']],
    ['fire_pit',{id:'p',at:[0,0],radius:2,fuel:'wood'},['Body']],
    ['fire_pit',{id:'g',at:[0,0],radius:2,fuel:'gas'},['Body','Top']],
    ['hardscape',{id:'h',polygon:square},['Surface']],
    ['hardscape',{id:'w',kind:'path',points:[[0,0],[9,0]],width:3,edging:'curb'},['Surface','Curb']],
    ['hardscape',{id:'j',kind:'path',points:[[0,0],[9,0]],width:3,pavers:{joint:'sand'}},['Surface','Joint']],
    ['beds',{id:'b',polygon:square},['Fill']],
    ['pool',{id:'pool',polygon:square},['Coping','Interior','Waterline tile','Water']],
    ['spa',{id:'spa',mode:'raised',polygon:square},['Coping','Interior','Waterline tile','Cladding','Water']],
    ['spa',{id:'flush',mode:'flush',polygon:square},['Coping','Interior','Waterline tile','Water']],
    ['edges',{id:'edge',polygon:square},['Strip']]]){
    const host=document.createElement('div'),sent=[];document.body.append(host);
    drawSiteShapeShelf(host,{kind,index:0,piece},{library,canEdit:()=>true,queue:work=>Promise.resolve().then(work),op:async o=>sent.push(o),
      report:e=>{throw e;},getKit:()=>input.kit,getRecord:()=>({kind,index:0,piece})});
    assert.deepEqual(host.querySelectorAll('[data-material-slot]').map(n=>n.dataset.materialSlot),parts,`${kind} slots`);
    if(!parts.length)continue;
    for(const label of parts){
      const slot=host.querySelector(`[data-material-slot="${label}"]`),before=sent.length;
      await useMaterial(slot,'wood_planks');
      const part={Boards:'boards',Posts:'posts',Rails:'rails',Body:'body',Top:'top',Surface:'surface',Curb:'edging',Joint:'joint',Fill:'fill',Coping:'coping',Interior:'interior','Waterline tile':'waterline',Cladding:'wall',Water:'water',Strip:'strip'}[label];
      assert.equal(sent.length,before+1);
      const operation=materials=>kind==='spa'?{op:'update_pool_feature',id:piece.id,materials}:{op:'update_site_shape',list:kind,index:0,materials};
      assert.deepEqual(sent.at(-1),operation({[part]:{id:'wood_planks'}}),`${kind} ${label}: one op, old payload`);
      await click(byText(slot,'Clear'));
      assert.equal(sent.length,before+2);assert.deepEqual(sent.at(-1),operation({[part]:null}));
    }
  }
  const host=document.createElement('div');document.body.append(host);
  drawSiteShapeShelf(host,{kind:'beds',index:0,piece:{id:'b',polygon:square,materials:{fill:{id:'wood_planks'}}}},{library,canEdit:()=>false,queue:w=>w(),op:()=>{throw Error('read-only wrote');},report:e=>{throw e;}});
  const slot=host.querySelector('[data-material-slot]');
  assert.ok(textOf(slot).includes('Wood planks'));assert.equal(slot.querySelectorAll('button,input').length,0,'read-only');
  console.log('Passed: yard shape card slots per feature, one op per choice, read-only');
}

// Real yard room card -> source feature -> shared material slot. Legacy rooms
// match their copied outline; new references survive an independent room move.
{
  const square=[[0,0],[6,0],[6,4],[0,4]], sent=[], selections=[];
  const plan={buildings:[],site:{pool:{id:'pool',polygon:square},hardscape:[{id:'patio',polygon:square.map(p=>[p[0]+20,p[1]])}],
    fire_pit:[{id:'pit',at:[40,0],radius:2,fuel:'gas'}],yard_rooms:[]}};
  let writable=true;
  const cards=createCards({getPlan:()=>plan,getKit:()=>input.kit,getLabel:()=> 'Yard room',library,canEdit:()=>writable,
    edit(){},op:async o=>sent.push(o),ask(){},select:s=>selections.push(s)});
  const host=document.getElementById('piece-card');
  for(const [kind,id,label,part,polygon] of [
    ['pool','pool','Pool','coping',square],
    ['hardscape','patio','Path / hardscape','surface',plan.site.hardscape[0].polygon],
    ['fire_pit','pit','Fire pit','body',Array.from({length:32},(_,i)=>[40+3.5*Math.cos(i*Math.PI/16),3.5*Math.sin(i*Math.PI/16)])]]){
    const room={id:'yard-'+id,name:'Yard room',polygon};plan.site.yard_rooms=[room];
    for(const referenced of [false,true]){
      if(referenced){room.feature={list:kind,id};room.polygon=polygon.map(p=>[p[0]+100,p[1]+100]);}
      cards.draw({pieceId:room.id,buildingId:null});
      const link=byText(host,`Edit ${label} materials`);assert.ok(link,`${id}: ${referenced?'referenced':'legacy'} room has a material link`);
      const before=sent.length;await click(link);assert.equal(sent.length,before,'navigation is not a history step');
      assert.deepEqual(selections.at(-1),{pieceId:id,buildingId:null});
      const slot=host.querySelector('[data-material-slot]');assert.ok(slot);
      await useMaterial(slot,'wood_planks');await cards.queue(async()=>{});
      assert.equal(sent.length,before+1);assert.deepEqual(sent.at(-1),{op:'update_site_shape',list:kind,index:0,materials:{[part]:{id:'wood_planks'}}});
    }
    writable=false;cards.draw({pieceId:room.id,buildingId:null});
    assert.ok(byText(host,`Edit ${label} materials`).disabled,'read-only room card');writable=true;
  }
  plan.site.yard_rooms=[{id:'gone',name:'Deleted source',polygon:square,feature:{list:'pool',id:'missing'}}];
  cards.draw({pieceId:'gone',buildingId:null});assert.equal(byText(host,'Edit Pool materials'),undefined,'deleted source never retargets a different feature');
  console.log('Passed: pool/patio/fire-pit yard room card links, legacy and moved references, no-op navigation, one material op, read-only and deleted source');
}

const square=[[0,0],[12,0],[12,8],[0,8]];
const room={id:'porch',kind:'porch',level:'L1',name:'Porch',polygon:square,foundation:{type:'posts'}};
const building={id:'b',position:[0,0],base:2,levels:[{id:'L1',elevation:0,ceiling:10}],rooms:[room],walls:[],openings:[],anchors:[],items:[],stairs:[]};
const plan={buildings:[building],site:{terraces:[]}};let writable=true;const ops=[];
window.showGlobalAlert=message=>errors.push(message);
const cards=createCards({getPlan:()=>plan,getKit:()=>input.kit,getLabel:()=> 'Porch',library,canEdit:()=>writable,edit(){},
 op:async operation=>{ops.push(structuredClone(operation));room.foundation=operation.foundation;},ask(){},select(){}});
cards.draw({pieceId:'porch',buildingId:'b'});const host=document.getElementById('piece-card');
const field=label=>host.querySelectorAll('input,select').find(n=>n.getAttribute('aria-label')===label);
const slot=label=>host.querySelector(`[data-material-slot="${label}"]`);
assert.ok(shown(field('Post width (in)'))&&shown(field('Post shape'))&&shown(field('Post spacing (ft)')));
assert.equal(field('Skirt'),undefined,'no Lattice/Panel selector');
assert.ok(!shown(slot('Skirt'))&&!shown(slot('Solid base'))&&shown(slot('Posts and beam')));
for(const [label,value,key]of [['Post width (in)','10','post_in'],['Post shape','round','post_shape'],['Post spacing (ft)','5','spacing_ft']]){
 const before=ops.length;field(label).value=value;await fire(field(label),'change');await cards.queue(async()=>{});
 assert.equal(ops.length,before+1);assert.equal(room.foundation[key],key==='post_shape'?value:Number(value));
}
field('Foundation').value='enclosed';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(shown(slot('Skirt'))&&shown(slot('Posts and beam'))&&!shown(slot('Solid base')));
assert.equal(field('Skirt'),undefined);
assert.ok(textOf(slot('Skirt')).includes('House default: Lattice'));
let before=ops.length;await useMaterial(slot('Skirt'),'wood_planks');await cards.queue(async()=>{});
assert.equal(ops.length,before+1);assert.deepEqual(room.foundation.materials.skirt,{id:'wood_planks'});
assert.equal(ops.at(-1).op,'set_porch_foundation');assert.equal(room.foundation.post_in,10,'material change preserves other fields');
await click(byText(slot('Skirt'),'Clear'));await cards.queue(async()=>{});
assert.equal(room.foundation.materials.skirt,null);assert.equal(ops.length,before+2);
assert.ok(textOf(slot('Skirt')).includes('House default: Lattice'));
await useMaterial(slot('Skirt'),'lattice');await cards.queue(async()=>{});
assert.deepEqual(room.foundation.materials.skirt,{id:'lattice'});assert.equal(ops.length,before+3);
assert.ok(!Object.hasOwn(ops.at(-1).foundation,'skirt'));
field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.ok(!shown(field('Post width (in)'))&&!shown(field('Post shape'))&&!shown(field('Post spacing (ft)')));
assert.ok(shown(slot('Solid base'))&&!shown(slot('Skirt'))&&!shown(slot('Posts and beam')));
field('Floor overhang (in)').value='2.5';await fire(field('Floor overhang (in)'),'change');await cards.queue(async()=>{});assert.equal(room.foundation.lip_in,2.5);
before=ops.length;
for(const [label,value]of [['Floor overhang (in)','5'],['Post width (in)','3'],['Post spacing (ft)','13']]){
 field(label).value=value;await fire(field(label),'change');await cards.queue(async()=>{});assert.equal(ops.length,before);
}
// Undo redraw and the grade note reflect current terrain/height, including auto base.
room.foundation=porchFoundation();cards.draw();assert.equal(field('Foundation').value,'posts');assert.ok(shown(field('Post width (in)')));
assert.ok(!textOf(host).includes('Slab on grade'));
building.base=.5;cards.draw();assert.ok(textOf(host).includes('Slab on grade'));
building.foundation={mode:'auto',offset_ft:2};cards.draw();assert.ok(!textOf(host).includes('Slab on grade'));
writable=false;cards.draw();assert.ok(field('Foundation').disabled);assert.equal(slot('Posts and beam').querySelectorAll('button,input').length,0);
field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});assert.equal(ops.length,before);
console.log('Passed: real card fields by type, post properties, default skirt role, slots/one op, ranges, undo, grade note and read-only');
"""

HOUSEHOLD = PRELUDE + r"""
const THREE=await import(three),{createTerrainTools}=await import(file('static/twin/editor/terrain_tools.js'));
const shell=document.createElement('div');shell.className='editor-shell';document.body.append(shell);
const canvas=document.createElement('canvas');shell.append(canvas);
const controls=new THREE.EventDispatcher();controls.enabled=true;
const view={renderer3:{domElement:canvas},scene:new THREE.Group(),camera:new THREE.PerspectiveCamera(50,1,.1,10000),
 controls,state:{view:'ext'},groups:{},setView(){},render(){}};
view.camera.position.set(4,200,4);view.camera.lookAt(0,0,0);view.camera.updateMatrixWorld();
const listeners=new Set(),library={selected:()=>null,onSelect:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},reveal:async()=>{}};
globalThis.fetch=async()=>new Response(JSON.stringify({materials:[],items:[]}));
const abort=new AbortController(),terrain=createTerrainTools({view,library,getPlan:()=>input.household,getKit:()=>input.kit,
 tools:{setTool(){},select(){}},canEdit:()=>true,signal:abort.signal,op:async()=>{throw Error('census wrote');}});
await test('real_household_pad_properties_render_every_existing_edge_slot',async()=>{
 const pads=input.household.site.terraces;assert.ok(Array.isArray(pads),'normalised household pad collection');let count=0;
 for(const pad of pads){
  terrain.choose('terraces',pad.id);const labels=[];
  for(const [i,edge]of (pad.edges||[]).entries()){
   if(edge.edge!=='sharp')continue;
   if(edge.wall){labels.push(`Edge ${i+1} Wall face`);if(edge.wall.cap)labels.push(`Edge ${i+1} Cap`);}
   else if(edge.stair){labels.push(`Edge ${i+1} Risers`);if(edge.stair.treads!==false)labels.push(`Edge ${i+1} Treads material`);}
   if((edge.wall||edge.stair)?.rail)labels.push(`Edge ${i+1} Railing material`);
  }
  assert.deepEqual(document.getElementById('terrain-card').querySelectorAll('[data-library-slot]').map(row=>row.dataset.librarySlot),labels,pad.id);
  assert.equal(listeners.size,labels.length,'only current household pad owns listeners');count+=labels.length;
 }
 terrain.cancel();assert.equal(listeners.size,0);abort.abort();
 console.log(`  household terrain: ${pads.length} pads / ${count} existing edge material rows`);
});finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    codes = []
    for driver in (REGRESSIONS, DRIVER):
        code, output = run_node(driver, {'root': ROOT.as_posix(), 'kit': kit})
        print(output)
        codes.append(code or 0)
    with tempfile.TemporaryDirectory(prefix='chauffeur_slot_terrain_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_library, twin_store
        twin_store.push_round(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')), 'build')
        code, output = run_node(HOUSEHOLD, {'root': ROOT.as_posix(), 'household': twin_store.current(), 'kit': twin_library.kit('modern_farmhouse')})
    print(output)
    codes.append(code or 0)
    sys.exit(max(codes))
