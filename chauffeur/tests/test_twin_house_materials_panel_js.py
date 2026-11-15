"""House defaults through the shared slot widget and real building card."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {houseMaterialsShelf}=await import(file('static/twin/editor/house_materials.js'));
const {KINDS,PANEL_ROLES}=await import(file('static/twin/surface_kinds.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {readLibraryCatalog}=await import(file('static/twin/editor/material_catalog.js'));
const entry={id:'material-household',name:'Family glass',color:'#abcdef'};
globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify({materials:[entry],items:[]})});
await readLibraryCatalog();
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
function make(locked=false){
 const building={id:'house',name:'House',materials:{},levels:[],rooms:[],walls:[],openings:[],items:[],anchors:[],stairs:[]};
 const plan={materials:{},buildings:[building],site:{terraces:[]}},host=document.createElement('div'),sent=[],errors=[];
 document.body.append(host);houseMaterialsShelf(host,building,{getPlan:()=>plan,getKit:()=>({materials:{}}),canEdit:()=>!locked,
  op:async o=>sent.push(o),report:e=>errors.push(e.message)});
 return {host,sent,errors,plan,building};
}
await test('panel_lists_every_kind_once',()=>{
 const {host}=make(),slots=host.querySelectorAll('[data-material-slot]');
 assert.equal(slots.length,PANEL_ROLES.length+KINDS.length);
 assert.deepEqual(slots.map(n=>n.dataset.materialSlot).sort(),['Siding','Interior walls','Floors',...KINDS.map(r=>r.label)].sort());
 assert.deepEqual(host.querySelectorAll('h4').map(textOf),['House materials','Walls and floors','Trim','Openings','Porch and stairs','Roof and ceilings','Fixtures','Yard']);
 assert.ok(textOf(host).includes('Default: Follows Trim'));assert.ok(textOf(host).includes('Default: Built-in glass'));assert.ok(textOf(host).includes('Default: House look'));
});
await test('choosing_a_material_sends_set_material',async()=>{
 const {host,sent,errors}=make(),slot=host.querySelector('[data-material-slot="Panes"]');
 await click(byText(slot,'Change'));await click(slot.querySelector('[data-material]'));
 assert.deepEqual(sent,[{op:'set_material',building:'house',target:{building:'house',role:'pane'},material:{id:entry.id}}]);
 await click(byText(slot,'Change'));await click(byText(slot,'Use default'));assert.equal(sent.length,2);assert.equal(sent[1].material,null);assert.deepEqual(errors,[]);
});
await test('site_kinds_use_the_site_target',async()=>{
 const {host,sent}=make();for(const role of ['water','lawn']){
  const slot=host.querySelector(`[data-material-slot="${KINDS.find(r=>r.kind===role).label}"]`);
  await click(byText(slot,'Change'));await click(slot.querySelector('[data-material]'));
  assert.deepEqual(sent.at(-1),{op:'set_material',building:'house',target:{site:true,role},material:{id:entry.id}});
 }
});
await test('tint_is_sent_with_the_slot',async()=>{
 const {host,sent}=make(),slot=host.querySelector('[data-material-slot="Panes"]');
 await click(byText(slot,'Change'));await click(slot.querySelector('[data-material]'));
 await click(byText(slot,'Change'));const tint=slot.querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');
 assert.deepEqual(sent.at(-1).material,{id:entry.id,color:'#123456'});
});
await test('read_only_shows_no_buttons',()=>{const {host}=make(true);assert.equal(host.querySelectorAll('button,input').length,0);});
await test('current_values_are_shown',()=>{
 const {host,building,plan}=make();building.materials.pane={id:entry.id};plan.materials.water={id:entry.id};host.replaceChildren();
 houseMaterialsShelf(host,building,{getPlan:()=>plan,getKit:()=>({}),canEdit:()=>false,op:()=>{throw Error('read only wrote');}});
 for(const label of ['Panes','Water'])assert.ok(textOf(host.querySelector(`[data-material-slot="${label}"]`)).includes('Family glass'));
});
await test('building_card_refreshes_house_and_site_values_and_read_only',async()=>{
 const {plan,building}=make();let writable=true;const sent=[];
 const cards=createCards({getPlan:()=>plan,getKit:()=>({}),getLabel:()=> 'House',canEdit:()=>writable,edit(){},op:async o=>sent.push(o),ask(){}});
 cards.draw({pieceId:'house',buildingId:'house'});const host=document.getElementById('piece-card');
 assert.ok(textOf(host).includes('House materials'));assert.ok(host.querySelector('[data-material-slot="Slab"]'));
 building.materials.pane={id:entry.id};plan.materials.water={id:entry.id};cards.draw();
 for(const label of ['Panes','Water'])assert.ok(textOf(host.querySelector(`[data-material-slot="${label}"]`)).includes('Family glass'));
 const slot=host.querySelector('[data-material-slot="Panes"]');await click(byText(slot,'Change'));await click(byText(slot,'Use default'));
 await cards.queue(async()=>{});assert.equal(sent.length,1);assert.equal(sent[0].material,null);
 writable=false;cards.draw();assert.equal(host.querySelector('[data-material-slot="Panes"]').querySelectorAll('button,input').length,0);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code or 0)
