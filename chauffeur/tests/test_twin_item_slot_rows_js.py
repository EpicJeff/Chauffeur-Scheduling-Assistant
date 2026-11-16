"""Selection cards reuse the material rows and send item-scoped operations."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON + r"""
const L=await import(file('static/twin/editor/library.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {siteMaterialSlots,drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
const p=fixture(),b=p.buildings[0],k=kit();
const material={id:'choice',name:'Family finish',color:'#456789',thumbnail_url:'test.jpg'};
globalThis.fetch=async url=>new Response(JSON.stringify(String(url).endsWith('/materials')?{materials:[material]}:{materials:[],items:[],imports:[]}));
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
 delete b.materials.pane;assert.match(lines('opening',b.openings[0]).find(l=>l.label==='Pane').text,/Built-in glass/);
});
const host=document.createElement('div');document.body.append(host);const canvas=document.createElement('canvas');host.append(canvas);
const view={scene:new THREE.Scene(),camera:new THREE.PerspectiveCamera(),renderer3:{domElement:canvas},controls:new THREE.EventDispatcher(),pick:()=>null};
const abort=new AbortController(),operations=[];let writable=true;
const library=L.createLibrary({view,kit:k,getPlan:()=>p,tools:{selection:()=>({}),select(){}},op:async operation=>operations.push(operation),canEdit:()=>writable,signal:abort.signal});
const cards=createCards({getPlan:()=>p,getKit:()=>k,getLabel:()=>'',canEdit:()=>writable,select(){},op:async operation=>operations.push(operation),
 edit:async()=>{},pickMaterial:library.pick,haLink:{draw(){},state:()=>({available:false})}});
const card=document.getElementById('piece-card');
await test('change_and_clear_send_the_item_target',async()=>{
 b.openings[0].materials={pane:{id:'blend'}};cards.draw({pieceId:'window',buildingId:'a'});
 click(card.querySelector('[aria-label="Change the pane material"]'));await wait();
 click(document.getElementById('library-entries').querySelector('[data-material="choice"]'));await wait();
 assert.equal(document.querySelector('#material-chooser'),null,'no scope chooser');
 assert.deepEqual(operations.at(-1),{op:'set_material',building:'a',target:{opening:'window',part:'pane'},material:{id:'choice'}});
 const row=card.querySelectorAll('.editor-material-line').find(r=>r.textContent.startsWith('Pane'));
 click(row.querySelectorAll('button').find(n=>n.textContent==='Clear'));await wait();
 assert.deepEqual(operations.at(-1),{op:'set_material',building:'a',target:{opening:'window',part:'pane'},material:null});
});
await test('room_and_roof_lines_still_listed',async()=>{
 const room={...b.rooms[0],wall_material:{id:'choice'}};
 assert.deepEqual(lines('room',room).map(l=>l.label),['Floor','Ceiling','Walls']);
 assert.equal(lines('roof',b.roof.sections[0])[0].label,'Roof');
});
await test('pool_and_spa_cards_list_water',async()=>{
 for(const [kind,piece,opName] of [['pool',p.site.pool,'update_site_shape'],['spa',p.site.pool.features[0],'update_pool_feature']]){
  assert.ok(siteMaterialSlots(kind,piece).some(([part,label])=>part==='water'&&label==='Water'));
  const parent=document.createElement('div');document.body.append(parent);
  drawSiteShapeShelf(parent,{kind,piece},{canEdit:()=>writable,queue:f=>f(),op:async operation=>operations.push(operation),report:e=>{throw e;},getKit:()=>k});
  click(parent.querySelector('[aria-label="Change the water material"]'));await wait();
  click(parent.querySelector('[data-material-slot="Water"] [data-material="choice"]'));await wait();
  assert.equal(operations.at(-1).op,opName);assert.deepEqual(operations.at(-1).materials,{water:{id:'choice'}});
 }
});
await test('read_only_card_has_no_buttons',async()=>{
 writable=false;cards.draw({pieceId:'window',buildingId:'a'});
 assert.equal(card.querySelectorAll('.editor-material-actions button').length,0);
 const before=operations.length;await library.pick(lines('opening',b.openings[0])[0].surface);assert.equal(operations.length,before);
});
abort.abort();finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)
