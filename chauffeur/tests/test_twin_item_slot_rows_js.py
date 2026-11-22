"""Selection cards reuse the material rows and send item-scoped operations."""
import json
import os
import sys
import tempfile
from test_twin_untouched_house_js import COMMON, ROOT, run_node
sys.path.insert(0, str(ROOT))

DRIVER = COMMON + r"""
const L=await import(file('static/twin/editor/library.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {siteMaterialSlots,drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
const p=fixture(),b=p.buildings[0],k=kit();
const material={id:'choice',name:'Family finish',color:'#456789',thumbnail_url:'test.jpg'};
const modelImports=['door','window'].map(kind=>({kind,id:'import-'+kind,name:'Imported '+kind,thumbnail_url:'import-'+kind+'.png'}));
globalThis.fetch=async url=>new Response(JSON.stringify(String(url).endsWith('/imports')?modelImports:String(url).endsWith('/materials')?{materials:[material]}:{materials:[],items:[],imports:[]}));
const wait=async()=>{await new Promise(r=>setTimeout(r,20));};
const lines=(kind,piece)=>L.materialLines({kind,piece,building:b},p,k);
await test('lines_per_item_type',async()=>{
 const window=b.openings[0],door=b.openings.find(o=>o.id==='door'),porch={id:'porch',kind:'porch',level:'L1',polygon:square(0,-8,16,8)};
 b.rooms.push(porch);b.porches[0].screened=true;
 const cases=[['opening',window,['window_frame','casing','pane'],'opening'],['opening',door,['door','casing','window_frame','pane'],'opening'],
  ['opening',{...door,glass:'none'},['door','casing','window_frame'],'opening'],['opening',b.openings.find(o=>o.id==='garage'),['garage_door','window_frame','casing'],'opening'],
  ['room',porch,['column','screen'],'porch'],['stair',{...b.stairs[0],style:'solid',rail:'none'},['stair_tread'],'stair'],
  ['stair',b.stairs[0],['stair_tread','stair_rail'],'stair'],['item',b.fixtures[0],['cabinet','counter'],'item'],
  ['item',b.fixtures[2],['shower_tile','shower_glass'],'item']];
 for(const [kind,piece,expected,target] of cases){
  const actual=lines(kind,piece).filter(l=>l.target?.part);assert.deepEqual(actual.map(l=>l.target.part),expected,kind+' '+piece.id);
  assert.ok(actual.every(l=>l.label&&l.text));
  for(const l of actual)assert.deepEqual(l.target,{[target]:piece.id,part:l.target.part});
 }
 b.porches[0].screened=false;assert.deepEqual(lines('room',porch).filter(l=>l.target?.part).map(l=>l.target.part),['column']);
 b.porches[0].screened=true;
});
await test('inherited_label_names_the_source',async()=>{
 const {readMaterialNames}=await import(file('static/twin/editor/material_catalog.js'));await readMaterialNames();
 b.materials.pane={id:'choice'};assert.match(lines('opening',b.openings[0]).find(l=>l.label==='Pane').text,/Family finish/);
 delete b.materials.pane;assert.equal(lines('opening',b.openings[0]).find(l=>l.label==='Pane').text,'House default: Glass');
});
const host=document.createElement('div');document.body.append(host);const canvas=document.createElement('canvas');host.append(canvas);
const view={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(),renderer3:{domElement:canvas},controls:new THREE.EventDispatcher(),pick:()=>null};
const abort=new AbortController(),operations=[];let writable=true;
const library=L.createLibrary({view,kit:k,getPlan:()=>p,tools:{selection:()=>({}),select(){}},op:async operation=>operations.push(operation),canEdit:()=>writable,signal:abort.signal});
const cards=createCards({getPlan:()=>p,getKit:()=>k,getLabel:()=>'',canEdit:()=>writable,select(){},op:async operation=>operations.push(operation),
 edit:async()=>{},library,pickMaterial:library.pick,haLink:{draw(){},state:()=>({available:false})}});
const card=document.getElementById('piece-card');
await test('selected_and_clear_send_the_item_target',async()=>{
 b.openings[0].materials={pane:{id:'blend'}};cards.draw({pieceId:'window',buildingId:'a'});
 library.select({kind:'material',...material});await wait();
 click(card.querySelector('[data-library-slot="Pane"] [data-slot-use]'));await wait();
 assert.equal(document.querySelector('#material-chooser'),null,'no scope chooser');
 assert.deepEqual(operations.at(-1),{op:'set_material',building:'a',target:{opening:'window',part:'pane'},material:{id:'choice'}});
 const row=card.querySelector('[data-library-slot="Pane"]');
 click(row.querySelector('[data-slot-clear]'));await wait();
 assert.deepEqual(operations.at(-1),{op:'set_material',building:'a',target:{opening:'window',part:'pane'},material:null});
});
await test('room_and_roof_lines_still_listed',async()=>{
 const room={...b.rooms[0],wall_material:{id:'choice'}};
 assert.deepEqual(lines('room',room).map(l=>l.label),['Floor','Ceiling','Walls']);
 assert.equal(lines('roof',b.roof.sections[0])[0].label,'Roof');
});
await test('card_rows_render_each_material_lines_provenance_including_house_look',async()=>{
 const room=b.rooms[0],roof=b.roof.sections[0];
 const saved={floor:room.floor_material,ceiling:room.ceiling_material,material:roof.material};
 try {
  room.floor_material={id:'choice'};delete room.ceiling_material;roof.material={id:'choice'};
  for(const [kind,piece] of [['room',room],['roof',roof],['opening',b.openings[0]]]){
   cards.draw({pieceId:piece.id,buildingId:b.id});await wait();
   for(const line of lines(kind,piece))assert.equal(card.querySelector(`[data-library-slot="${line.label}"] [data-slot-name]`).textContent,line.text,kind+' '+line.label);
  }
  cards.draw({pieceId:room.id,buildingId:b.id});await wait();
  assert.match(card.querySelector('[data-library-slot="Floor"] [data-slot-name]').textContent,/Family finish, set here/);
  assert.equal(card.querySelector('[data-library-slot="Ceiling"] [data-slot-name]').textContent,'House default: Ceiling');
 } finally {room.floor_material=saved.floor;room.ceiling_material=saved.ceiling;roof.material=saved.material;}
});
await test('pool_and_spa_cards_list_water',async()=>{
 for(const [kind,piece,opName] of [['pool',p.site.pool,'update_site_shape'],['spa',p.site.pool.features[0],'update_pool_feature']]){
  assert.ok(siteMaterialSlots(kind,piece).some(([part,label])=>part==='water'&&label==='Water'));
  const parent=document.createElement('div');document.body.append(parent);
  drawSiteShapeShelf(parent,{kind,piece},{library,ownSlot:row=>row,canEdit:()=>writable,queue:f=>f(),op:async operation=>operations.push(operation),report:e=>{throw e;},getKit:()=>k});
  click(parent.querySelector('[data-library-slot="Water"] [data-slot-use]'));await wait();
  assert.equal(operations.at(-1).op,opName);assert.deepEqual(operations.at(-1).materials,{water:{id:'choice'}});
 }
});
await test('every_card_slot_preserves_the_old_assignment_clear_and_reset_operations',async()=>{
 const originalReveal=library.reveal,revealed=[];library.reveal=async(kind,id)=>revealed.push({kind,id});
 const dormer={id:'test-dormer',kind:'gable',level:'L2',rect:[2,2,6,8],material:{id:'choice'}};b.dormers.push(dormer);
 b.rooms[0].wall_material={id:'choice'};
 const cases=[['wall',b.walls[0]],['room',b.rooms[0]],['roof',b.roof.sections[0]],['dormer',dormer],
  ...b.openings.map(piece=>['opening',piece]),['stair',b.stairs[0]],['porch',b.porches[0]],...b.fixtures.map(piece=>['fixture',piece])];
 const covered=[];
 for(const [kind,piece] of cases){
  // Give every old Clear control a real override, including both wall faces.
  if(kind==='wall')piece.faces={left:{id:'choice'},right:{id:'choice'}};
  else if(kind==='room'){piece.floor_material={id:'choice'};piece.ceiling_material={id:'choice'};}
  else if(['roof','dormer'].includes(kind))piece.material={id:'choice'};
  else piece.materials=Object.fromEntries(lines(kind,piece).map(line=>[line.target.part,{id:'choice'}]));
  cards.draw({pieceId:piece.id,buildingId:b.id});await wait();
  const oldLines=lines(kind,piece),rows=card.querySelectorAll('[data-library-slot]').filter(row=>oldLines.some(line=>line.label===row.dataset.librarySlot));
  assert.equal(rows.length,oldLines.length,kind+' '+piece.id+' row census');
  for(const [i,line] of oldLines.entries()){
   const row=rows[i];covered.push(kind+':'+(line.target.part||line.target.surface||line.target.side||line.label));
   assert.equal(row.dataset.librarySlot,line.label);assert.match(row.querySelector('[data-slot-name]').textContent,/Family finish/);
   const swatch=row.querySelector('[data-slot-swatch]');assert.ok(swatch,'current swatch '+covered.at(-1));
   assert.equal(swatch.getAttribute('aria-label'),`Show the ${line.label.toLowerCase()} material in the Library`);
   assert.equal(swatch.querySelector('img').src,'test.jpg');
   click(swatch);await wait();assert.deepEqual(revealed.at(-1),{kind:'material',id:'choice'},covered.at(-1)+' reveals current asset');
   assert.equal(row.querySelector('[data-slot-use]').getAttribute('aria-label'),'Use Family finish');
   // Before choosing, Clear appears only where this row already has a local override (roof slopes inherit).
   assert.equal(!!row.querySelector('[data-slot-clear]'),!!line.clear,covered.at(-1)+' Clear only where set');
   const before=operations.length;click(row.querySelector('[data-slot-use]'));await wait();
   assert.equal(operations.length,before+1,covered.at(-1)+' applies once');
   assert.deepEqual(operations.at(-1),L.surfaceOperation(line.surface,'face',material),covered.at(-1)+' old choose payload');
   // After choosing a material on this row, Clear becomes available; clicking a focused Clear returns focus to Use.
   const clearHere=row.querySelector('[data-slot-clear]');assert.ok(clearHere,covered.at(-1)+' Clear appears once set');
   clearHere.focus();
   click(clearHere);await wait();
   assert.deepEqual(operations.at(-1),{op:'set_material',building:b.id,target:line.target,material:null},covered.at(-1)+' old Clear payload');
   assert.equal(row.querySelector('[data-slot-clear]'),null,covered.at(-1)+' Clear hides after clearing');
   assert.equal(document.activeElement,row.querySelector('[data-slot-use]'),covered.at(-1)+' detaching focused Clear moves focus to Use');
  }
 }
 for(const site of ['wall:left','wall:right','room:floor','room:ceiling','room:walls','roof:Roof','dormer:Roof',
  'opening:door','opening:garage_door','opening:window_frame','opening:casing','opening:pane','stair:stair_tread','stair:stair_rail',
  'porch:column','porch:screen','fixture:cabinet','fixture:counter','fixture:shower_tile','fixture:shower_glass'])assert.ok(covered.includes(site),site);
 // Both kinds of inherited reset retain exactly the previous target and label.
 delete b.rooms[1].floor_material;delete b.rooms[1].ceiling_material;
 for(const owner of [b.levels[1],b]){
  delete b.levels[1].materials;delete b.materials.floor;owner.materials={...(owner.materials||{}),floor:{id:'choice'}};
  cards.draw({pieceId:b.rooms[1].id,buildingId:b.id});await wait();
  const line=lines('room',b.rooms[1]).find(line=>line.label==='Floor'),row=card.querySelector('[data-library-slot="Floor"]');
  assert.ok(line.reset);assert.equal(row.querySelector('[data-slot-reset]').textContent,line.reset.label);
  click(row.querySelector('[data-slot-reset]'));await wait();
  assert.deepEqual(operations.at(-1),{op:'set_material',building:b.id,target:line.reset.target,material:null});
 }
 library.reveal=originalReveal;
});
await test('model_rows_accept_only_the_matching_import_or_manifest_kind_and_clear_to_generated',async()=>{
 const {readFileSync}=await import('node:fs');window.twinObjectSchema=JSON.parse(readFileSync(input.root+'/static/twin/object_schema.json','utf8'));
 const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
 for(const kind of ['door','window']){
  const piece=b.openings.find(piece=>piece.kind===kind);piece.model='manifest-'+kind;
  window.twinManifest={['manifest-'+kind]:{kind:'model',object_kind:kind,name:'Manifest '+kind,thumbnail:'preview.png'},
   ['category-'+kind]:{kind:'model',category:kind,name:'Category '+kind,thumbnail:'category.png'}};
  const parent=document.createElement('div');document.body.append(parent);
  const slots=[];drawObjectShelf(parent,{piece,building:b,kind:'opening'},{library,ownSlot:row=>slots.push(row),canEdit:()=>true,queue:f=>Promise.resolve().then(f),
   op:async operation=>operations.push(operation),report:e=>{throw e;}});await wait();
  const row=parent.querySelector('[data-library-slot="Model"]');assert.ok(row,'Model row for '+kind);
  assert.match(row.querySelector('[data-slot-name]').textContent,/Manifest/);assert.ok(row.querySelector('[data-slot-swatch] img'));
  for(const entry of [{kind:'material',id:'choice',name:'Finish'},{kind:kind==='door'?'window':'door',id:'import-wrong',name:'Wrong model'},
   {kind:kind==='door'?'window':'door',object_kind:kind,id:'import-conflict',name:'Wrong import metadata'}]){
   library.select(entry);assert.equal(row.querySelector('[data-slot-use]').disabled,true);assert.equal(row.querySelector('[data-slot-use]').textContent,'Use selected');
  }
  for(const entry of [{kind,id:'import-'+kind,name:'Imported '+kind},{kind:'furniture',id:'manifest-'+kind,name:'Manifest '+kind,object_kind:kind},
   {kind:'furniture',id:'category-'+kind,name:'Category '+kind,category:kind}]){
   library.select(entry);assert.equal(row.querySelector('[data-slot-use]').disabled,false,entry.id);
   click(row.querySelector('[data-slot-use]'));await wait();
   assert.deepEqual(operations.at(-1),{op:'set_object',building:b.id,id:piece.id,properties:{model:entry.id}});
   assert.equal(row.querySelector('[data-slot-name]').textContent,entry.name,entry.id+' current name');
   assert.ok(row.querySelector('[data-slot-swatch] img'),entry.id+' current thumbnail');
  }
  click(row.querySelector('[data-slot-clear]'));await wait();
  assert.deepEqual(operations.at(-1),{op:'set_object',building:b.id,id:piece.id,properties:{model:null}});
  assert.equal(row.querySelector('[data-slot-name]').textContent,'Generated');assert.equal(row.querySelector('[data-slot-swatch]').disabled,true);
  slots.forEach(slot=>slot.dispose());parent.remove();
 }
});
await test('every_card_material_target_supports_inherited_tint_offset_and_independent_resets',async()=>{
 const cases=[['wall',b.walls[0]],['room',b.rooms[0]],['roof',b.roof.sections[0]],['dormer',b.dormers.at(-1)],
  ...b.openings.map(p=>['opening',p]),['stair',b.stairs[0]],['porch',b.porches[0]],...b.fixtures.map(p=>['fixture',p])];
 for(const [kind,piece] of cases){
  cards.draw({pieceId:piece.id,buildingId:b.id});await wait();
  for(const line of lines(kind,piece)){
   const row=card.querySelector(`[data-library-slot="${line.label}"]`),expected=material=>({op:'set_material',building:b.id,target:line.target,material});
   // Start from the inherited state; an inherited row has no Clear (nothing is set there).
   const clearHere=row.querySelector('[data-slot-clear]');assert.equal(!!clearHere,!!line.clear,kind+' '+line.label+' Clear only where set');
   if(clearHere){click(clearHere);await wait();}
   const tint=row.querySelector('input[type="color"]'),u=row.querySelector('[data-slot-u]'),rot=row.querySelector('[data-slot-rotation]');
   assert.ok(tint&&u&&rot,kind+' '+line.label+' complete controls');
   tint.value='#123456';tint.dispatchEvent(new Event('change'));await wait();assert.deepEqual(operations.at(-1),expected({color:'#123456'}));
   u.value='-.05';u.dispatchEvent(new Event('change'));await wait();
   rot.value='90';rot.dispatchEvent(new Event('change'));await wait();
   const uv={u:.95,v:0,rot:90};assert.deepEqual(operations.at(-1),expected({color:'#123456',uv}));
   click(row.querySelectorAll('button').find(n=>n.textContent==='Clear override'));await wait();assert.deepEqual(operations.at(-1),expected({uv}));
   click(row.querySelector('[data-slot-offset-reset]'));await wait();assert.deepEqual(operations.at(-1),expected(null));
  }
 }
});
await test('read_only_card_has_no_buttons',async()=>{
 writable=false;cards.draw({pieceId:'window',buildingId:'a'});
 assert.equal(card.querySelectorAll('.editor-material-actions button').length,0);
 const before=operations.length;await library.pick(lines('opening',b.openings[0])[0].surface);assert.equal(operations.length,before);
});
abort.abort();finish();
"""

HOUSEHOLD = COMMON + r"""
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {materialLines}=await import(file('static/twin/editor/library.js'));
const {siteRecords}=await import(file('static/twin/objects.js'));
const {siteMaterialSlots}=await import(file('static/twin/editor/site_shape_shelf.js'));
window.twinObjectSchema=JSON.parse((await import('node:fs')).readFileSync(input.root+'/static/twin/object_schema.json','utf8'));
globalThis.fetch=async()=>new Response(JSON.stringify([]));
const listeners=new Set(),library={selected:()=>null,onSelect:fn=>{listeners.add(fn);return()=>listeners.delete(fn);},reveal:async()=>{}};
const cards=createCards({getPlan:()=>input.household,getKit:()=>input.houseKit,getLabel:()=>'',canEdit:()=>true,select(){},op:async()=>{},edit:async()=>{},library,
 haLink:{draw(){},state:()=>({available:false,devices:[]})}}),card=document.getElementById('piece-card');
const census={wall:0,room:0,roof:0,opening:0,building:0,site:0};let rows=0;
await test('every_real_household_property_card_renders_its_material_rows',async()=>{
 for(const building of input.household.buildings){
  for(const [kind,pieces] of [['building',[building]],['wall',building.walls],['room',building.rooms],['roof',building.roof?.sections],
   ['roof',building.roofs],['dormer',building.dormers],['opening',building.openings],['stair',building.stairs],['item',building.items],
   ['fixture',building.fixtures],['porch',building.porches]])for(const piece of pieces||[]){
    cards.draw({pieceId:piece.id,buildingId:building.id});
    const expected=materialLines({kind,piece,building},input.household,input.houseKit);
    for(const line of expected){
     const row=card.querySelector(`[data-library-slot="${line.label}"]`);assert.ok(row,kind+' '+piece.id+' '+line.label);
     assert.equal(row.querySelector('[data-slot-name]').textContent,line.text);
     assert.equal(row.querySelector('[data-slot-name]').getAttribute('aria-disabled'),String(line.inherited));
     assert.ok(row.querySelector('input[type="color"]')&&row.querySelector('[data-slot-u]')&&row.querySelector('[data-slot-v]')&&row.querySelector('[data-slot-rotation]'));
    }
    rows+=expected.length;if(kind in census)census[kind]++;
   }
 }
 for(const record of [...siteRecords(input.household),...(input.household.site?.pool?.features||[]).map(piece=>({piece,kind:piece.kind}))]){
  cards.draw({pieceId:record.piece.id});
  for(const [,label] of siteMaterialSlots(record.kind,record.piece)){assert.ok(card.querySelector(`[data-library-slot="${label}"]`),record.kind+' '+label);rows++;}
  census.site++;
 }
 for(const [kind,count] of Object.entries(census))assert.ok(count>0,'fixture contains '+kind);
 assert.ok(rows>100,'real house exercises a broad row census');cards.draw(null);assert.equal(listeners.size,0,'all replaced rows unsubscribe');
 console.log('  household cards '+JSON.stringify(census)+' / '+rows+' material rows');
});finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    if code:
        sys.exit(code)
    with tempfile.TemporaryDirectory(prefix='chauffeur_slot_rows_', ignore_cleanup_errors=True) as scratch:
        os.environ['CHAUFFEUR_DATA_DIR'] = scratch
        from services import twin_library, twin_store
        twin_store.push_round(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')), 'build')
        code, output = run_node(HOUSEHOLD, {'root': ROOT.as_posix(), 'household': twin_store.current(), 'houseKit': twin_library.kit('modern_farmhouse')}, timeout=180)
    print(output)
    sys.exit(code or 0)
