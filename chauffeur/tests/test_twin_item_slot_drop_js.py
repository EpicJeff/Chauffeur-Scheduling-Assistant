"""Material drops exercise the editor handler and real batched part raycasts."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON + r"""
const {createLibrary,materialLines,surfaceOperation}=await import(file('static/twin/editor/library.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const p=fixture(),b=p.buildings[0],k=kit();
b.items=b.fixtures.map(f=>({...f,host:{floor:'r1',u:.5,v:.5}}));
const porch={id:'porch',kind:'porch',level:'L1',polygon:b.porches[0].polygon};b.rooms.push(porch);
const host=document.createElement('div');document.body.append(host);const canvas=document.createElement('canvas');host.append(canvas);
const camera=new THREE.PerspectiveCamera(38,1440/900,.1,1000);camera.position.set(6,6,20);camera.lookAt(6,1,0);camera.updateMatrixWorld(true);
let hit=null,writable=true;const operations=[],abort=new AbortController();
const view={scene:new THREE.Scene(),camera,renderer3:{domElement:canvas},controls:new THREE.EventDispatcher(),pick:()=>hit};
globalThis.fetch=async url=>new Response(JSON.stringify(String(url).endsWith('/manifest')?{revision:1,entries:k.manifest}
 :String(url).endsWith('/materials')?{materials:[{id:'choice',name:'Family finish',thumbnail_url:'test.jpg'}]}:{materials:[],items:[],imports:[]}));
const library=createLibrary({view,kit:k,getPlan:()=>p,tools:{selection:()=>({}),select(){}},op:async operation=>operations.push(operation),canEdit:()=>writable,signal:abort.signal});
const wait=async()=>{await new Promise(r=>setTimeout(r,20));};
document.getElementById('library-panel').hidden=true;click(document.getElementById('rail-library'));await wait();
const event={clientX:700,clientY:450};
function pick(kind,id,part){hit={kind,id,pieceId:id,building:'a',buildingId:'a',part,point:[4,2,0]};return library.surfaceAt(event);}
async function drop(kind,id,part){pick(kind,id,part);const tile=document.getElementById('library-entries').querySelector('[data-material="choice"]');
 document.elementFromPoint=()=>canvas;fire(tile,'pointerdown',{button:0,pointerId:4,clientX:100,clientY:100});
 fire(document,'pointerup',{pointerId:4,...event});await wait();return operations.at(-1);}
await test('drop_on_a_pane_targets_the_opening',async()=>{
 const surface=pick('opening','window','pane');assert.deepEqual(surface.target,{opening:'window',part:'pane'});
 assert.match(surface.label,/window.*pane/i);assert.deepEqual((await drop('opening','window','pane')).target,surface.target);
});
await test('drop_on_a_frame_targets_the_frame',async()=>{
 assert.deepEqual((await drop('opening','window','window_frame')).target,{opening:'window',part:'window_frame'});
});
await test('drop_on_garage_parts_keeps_the_part_under_the_pointer',async()=>{
 for(const part of ['garage_door','pane','window_frame','casing'])
  assert.deepEqual((await drop('opening','garage',part)).target,{opening:'garage',part});
});
await test('drop_on_an_untagged_opening_still_goes_to_the_wall',async()=>{
 const surface=pick('opening','window');assert.equal(surface.kind,'wall');assert.equal(surface.piece.id,'L1w0');
});
await test('drop_on_a_light_or_anchor_still_redirects',async()=>{
 for(const kind of ['light','anchor']){b.anchors=[{id:'marker',host:{wall:'L1w0',side:'left',at:4,z:4}}];assert.equal(pick(kind,'marker').piece.id,'L1w0');}
 assert.equal(pick('item','kitchen').piece.id,'r1');
});
await test('drop_on_stair_column_cabinet_and_ceiling',async()=>{
 for(const [kind,id,part,target] of [['stair','stairs','stair_rail',{stair:'stairs',part:'stair_rail'}],
  ['porch','porch','column',{porch:'porch',part:'column'}],['fixture','kitchen','counter',{item:'kitchen',part:'counter'}]])
  assert.deepEqual((await drop(kind,id,part)).target,target);
 const ceiling=pick('room','r1','ceiling');assert.equal(ceiling.surface,'ceiling');assert.equal(ceiling.role,'ceiling');
});
await test('drop_on_pool_water_sends_the_site_shape_op',async()=>{
 for(const [kind,id,opName] of [['pool','pool','update_site_shape'],['spa','spa','update_pool_feature']]){
  const op=await drop(kind,id,'water');assert.equal(op.op,opName);assert.deepEqual(op.materials,{water:{id:'choice'}});assert.equal(op.id,id);
 }
});
await test('no_scope_chooser_for_item_drops',async()=>{
 document.querySelector('#material-chooser')?.remove();await drop('opening','window','pane');assert.equal(document.querySelector('#material-chooser'),null);
});
await test('read_only_editor_ignores_item_drops',async()=>{
 writable=false;const before=operations.length;await drop('opening','window','pane');assert.equal(operations.length,before);writable=true;
});
await test('tile_pointer_drops_on_every_card_row_keep_the_old_face_payload_and_selection',async()=>{
 const cards=createCards({getPlan:()=>p,getKit:()=>k,getLabel:()=>'',canEdit:()=>writable,select(){},op:async operation=>operations.push(operation),edit:async()=>{},library,
  haLink:{draw(){},state:()=>({available:false})}}),card=document.getElementById('piece-card');
 b.rooms[0].wall_material={id:'choice'};b.porches[0].screened=true;
 const dormer={id:'row-dormer',kind:'gable',level:'L2',rect:[1,1,5,7]};b.dormers.push(dormer);
 const cases=[['wall',b.walls[0]],['room',b.rooms[0]],['roof',b.roof.sections[0]],['dormer',dormer],
  ...b.openings.map(piece=>['opening',piece]),['stair',b.stairs[0]],['porch',b.porches[0]],...b.fixtures.map(piece=>['fixture',piece])];
 const selected={kind:'furniture',id:'other-selected',name:'Selected chair'};library.select(selected);
 for(const [kind,piece] of cases){
  cards.draw({pieceId:piece.id,buildingId:b.id});await wait();
  const lines=materialLines({kind,piece,building:b},p,k),rows=card.querySelectorAll('[data-library-slot]').filter(row=>lines.some(line=>line.label===row.dataset.librarySlot));
  assert.equal(rows.length,lines.length,kind+' '+piece.id);
  for(const [index,line] of lines.entries()){
   const row=rows[index],before=operations.length,tile=document.getElementById('library-entries').querySelector('[data-material="choice"]');
   assert.ok(row.querySelector('[data-slot-use]').disabled,'wrong selected kind stays disabled');
   document.elementFromPoint=()=>row.querySelector('[data-slot-swatch]');
   fire(tile,'pointerdown',{button:0,pointerId:31,clientX:100,clientY:100});
   fire(document,'pointermove',{pointerId:31,clientX:500,clientY:400});
   assert.ok(row.classList.contains('editor-slot-dragover'),kind+' '+line.label+' accepts material drag');
   fire(document,'pointerup',{pointerId:31,clientX:500,clientY:400});await wait();
   assert.equal(operations.length,before+1);assert.deepEqual(operations.at(-1),surfaceOperation(line.surface,'face',{id:'choice'}),kind+' '+line.label);
   assert.equal(library.selected().id,selected.id,'drag never changes Library selection');
   assert.equal(document.querySelector('#material-chooser'),null,'row never opens the 3D scope chooser');
  }
 }
 cards.draw(null);
});
await test('row_drop_ignores_the_wrong_kind_and_read_only_assignment',async()=>{
 const {createSlotRow}=await import(file('static/twin/editor/slot_row.js'));
 const row=createSlotRow({label:'Frame',library,accepts:entry=>entry.kind==='material',current:()=>null,apply:async entry=>operations.push({id:entry.id}),clear:async()=>{}});
 document.body.append(row.element);const before=operations.length;
 row.element.dispatchEvent(new CustomEvent('chf-library-slot-drag',{detail:{phase:'over',entry:{kind:'door',id:'import-door'}}}));
 assert.equal(row.element.classList.contains('editor-slot-dragover'),false);
 row.element.dispatchEvent(new CustomEvent('chf-library-slot-drag',{detail:{phase:'drop',entry:{kind:'door',id:'import-door'}}}));await wait();
 assert.equal(operations.length,before);row.dispose();row.element.remove();
 // Exercise the domain owner's read-only check through the actual card row.
 const cards=createCards({getPlan:()=>p,getKit:()=>k,getLabel:()=>'',canEdit:()=>writable,select(){},op:async operation=>operations.push(operation),edit:async()=>{},library,
  haLink:{draw(){},state:()=>({available:false})}});
 writable=false;cards.draw({pieceId:'window',buildingId:b.id});
 for(const node of document.getElementById('piece-card').querySelectorAll('[data-library-slot]'))
  node.dispatchEvent(new CustomEvent('chf-library-slot-drag',{detail:{phase:'drop',entry:{kind:'material',id:'choice'}}}));
 await wait();assert.equal(operations.length,before);writable=true;cards.draw(null);
});
abort.abort();
const {mountTwin}=await import(file('static/twin/twin_view.js'));
await test('real_pick_distinguishes_pane_frame_and_casing_after_batching',async()=>{
 const plan=fixture();plan.buildings=[plan.buildings[0]];plan.buildings[0].porches=[];plan.site={};
 const el=document.createElement('div');document.body.append(el);const v=await mountTwin(el,{plan,kit:k,tier:'low',bake:false});
 v.setCamera('front');v.setCameraState({position:[4*G.FT,5*G.FT,30*G.FT],target:[4*G.FT,5*G.FT,0]});
 const at=(x,y)=>{const q=new THREE.Vector3(x*G.FT,y*G.FT,.15*G.FT).project(v.camera),r=v.renderer3.domElement.getBoundingClientRect();return v.pick(r.left+(q.x+1)*r.width/2,r.top+(1-q.y)*r.height/2);};
 for(const [x,y,part] of [[3,6,'pane'],[2.5,6,'window_frame'],[2.25,6,'casing']]){
  const hit=at(x,y);assert.equal(hit?.pieceId,'window',JSON.stringify(hit));assert.equal(hit.part,part,JSON.stringify(hit));
 }
 v.dispose();
});
await test('real_garage_pick_distinguishes_solid_glass_frame_and_casing',async()=>{
 const plan=fixture();plan.buildings=[plan.buildings[0]];plan.buildings[0].porches=[];plan.site={};
 plan.buildings[0].openings.find(o=>o.id==='garage').lites='top';
 const el=document.createElement('div');document.body.append(el);const v=await mountTwin(el,{plan,kit:k,tier:'low',bake:false});
 v.setCamera('front');v.setCameraState({position:[31*G.FT,5*G.FT,30*G.FT],target:[31*G.FT,5*G.FT,0]});
 for(const [x,y,part] of [[29,5,'garage_door'],[29,8,'pane'],[27.07,5,'window_frame'],[26.75,5,'casing']]){
  const q=new THREE.Vector3(x*G.FT,y*G.FT,.15*G.FT).project(v.camera),r=v.renderer3.domElement.getBoundingClientRect();
  const hit=v.pick(r.left+(q.x+1)*r.width/2,r.top+(1-q.y)*r.height/2);
  assert.equal(hit?.pieceId,'garage',JSON.stringify(hit));assert.equal(hit.part,part,JSON.stringify(hit));
 }
 v.dispose();
});
await test('real_pool_and_spa_water_picks_survive_yard_reuse',async()=>{
 const plan=fixture();plan.buildings=[];
 const el=document.createElement('div');document.body.append(el);const v=await mountTwin(el,{plan,kit:k,tier:'low',bake:false});
 const halt=new AbortController();
 const picker=createLibrary({view:v,kit:k,getPlan:()=>plan,tools:{selection:()=>({}),select(){}},op:async()=>{},canEdit:()=>true,signal:halt.signal});
 const at=async(x,y,expected)=>{
  v.setCameraState({position:[x*G.FT,40*G.FT,-(y-.001)*G.FT],target:[x*G.FT,0,-y*G.FT]});
  const r=v.renderer3.domElement.getBoundingClientRect(),hit=v.pick(r.left+r.width/2,r.top+r.height/2,{water:true});
  assert.equal(v.pick(r.left+r.width/2,r.top+r.height/2),null,'other tools still see open ground');
  assert.equal(hit?.kind,expected,JSON.stringify(hit));assert.equal(hit.part,'water');
  if(expected==='pool')assert.equal(picker.pickSite(r.left+r.width/2,r.top+r.height/2)?.id,'pool','water keeps the existing pool selection path');
 };
 await at(18,42,'pool');await at(9,41,'spa');
 await v.rebuild(structuredClone(plan));await at(9,41,'spa');
 plan.site.pool.features[0].materials={water:{id:'choice'}};await v.rebuild(plan);await at(9,41,'spa');
 halt.abort();v.dispose();
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)
