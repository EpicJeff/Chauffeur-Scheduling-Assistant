"""House defaults through the shared slot widget and real building card."""
import sys
import json
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const slotListeners=new Set();let selectedMaterial=null;
const library={selected:()=>selectedMaterial,onSelect:fn=>{slotListeners.add(fn);return()=>slotListeners.delete(fn);},reveal:async()=>{}};
async function useMaterial(slot,id){selectedMaterial={kind:'material',id,name:id};for(const fn of slotListeners)fn();await click(slot.querySelector('[data-slot-use]'));}

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
 document.body.append(host);houseMaterialsShelf(host,building,{getPlan:()=>plan,getKit:()=>({materials:{}}),library,canEdit:()=>!locked,
  op:async o=>sent.push(o),report:e=>errors.push(e.message)});
 return {host,sent,errors,plan,building};
}
await test('grass_choice_load_save_refusal_read_only_and_disposal',async()=>{
 const {plan,building}=make(),host=document.createElement('div'),calls=[],errors=[],owned=[];
 let fail=false,editable=true;
 const settingsRequest=async(path,method,body,area)=>{
  calls.push({path,method,body,area});if(fail)throw Error('Grass refused');
  return {lawn:{grass_type:'warm'}};
 };
 houseMaterialsShelf(host,building,{getPlan:()=>plan,getKit:()=>({}),library,ownSlot:row=>owned.push(row),
  canEdit:()=>editable,op:()=>{throw Error('grass must not write the house')},report:e=>errors.push(e.message),settingsRequest});
 const choice=host.querySelector('[name="lawn_grass_type"]');assert.ok(choice);assert.equal(choice.disabled,true);
 await new Promise(r=>setTimeout(r,0));assert.equal(choice.value,'warm');assert.equal(choice.disabled,false);
 assert.match(textOf(choice),/Bermuda, zoysia, St. Augustine/);assert.match(textOf(choice),/fescue, bluegrass, rye/);
 choice.value='cool';await fire(choice,'change');await new Promise(r=>setTimeout(r,0));
 assert.deepEqual(calls.at(-1),{path:'weather-sources',method:'PUT',body:{lawn_grass_type:'cool'},area:'twin'});
 fail=true;choice.value='warm';await fire(choice,'change');await new Promise(r=>setTimeout(r,0));
 assert.equal(choice.value,'cool');assert.deepEqual(errors,['Grass refused']);
 fail=false;editable=false;const before=calls.length;await fire(choice,'change');assert.equal(calls.length,before);
 editable=true;owned.forEach(row=>row.dispose());await fire(choice,'change');assert.equal(calls.length,before);
});
await test('panel_lists_every_kind_once',()=>{
 const {host}=make(),slots=host.querySelectorAll('[data-material-slot]');
 assert.equal(slots.length,PANEL_ROLES.length+KINDS.length);
 assert.deepEqual(slots.map(n=>n.dataset.materialSlot).sort(),['Siding','Interior walls','Floors',...KINDS.map(r=>r.label)].sort());
 assert.deepEqual(host.querySelectorAll('h4').map(textOf),['House materials','Walls and floors','Trim','Openings','Porch and stairs','Roof and ceilings','Fixtures','Yard']);
 assert.ok(textOf(host).includes('Default: Follows Trim'));assert.ok(textOf(host).includes('Default: Built-in glass'));assert.ok(textOf(host).includes('Default: House look'));
});
await test('choosing_a_material_sends_set_material',async()=>{
 const {host,sent,errors}=make(),slot=host.querySelector('[data-material-slot="Panes"]');
 await useMaterial(slot,entry.id);
 assert.deepEqual(sent,[{op:'set_material',building:'house',target:{building:'house',role:'pane'},material:{id:entry.id}}]);
 await click(byText(slot,'Clear'));assert.equal(sent.length,2);assert.equal(sent[1].material,null);assert.deepEqual(errors,[]);
});
await test('site_kinds_use_the_site_target',async()=>{
 const {host,sent}=make();for(const role of ['water','lawn']){
  const slot=host.querySelector(`[data-material-slot="${KINDS.find(r=>r.kind===role).label}"]`);
  await useMaterial(slot,entry.id);
  assert.deepEqual(sent.at(-1),{op:'set_material',building:'house',target:{site:true,role},material:{id:entry.id}});
 }
});
await test('every_house_role_preserves_apply_clear_and_tint_payloads',async()=>{
 const {host,sent}=make();
 for(const row of [...PANEL_ROLES.map(kind=>({kind,label:{siding:'Siding',interior_wall:'Interior walls',floor:'Floors',porch_ceiling:'Porch ceiling'}[kind]})),...KINDS]){
  const slot=host.querySelector(`[data-library-slot="${row.label}"]`);assert.ok(slot,row.kind);
  const target=row.scope==='site'?{site:true,role:row.kind}:{building:'house',role:row.kind};
  const expected=material=>({op:'set_material',building:'house',target,material});
  await useMaterial(slot,entry.id);assert.deepEqual(sent.at(-1),expected({id:entry.id}),row.kind+' assignment payload unchanged');
  const tint=slot.querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');
  assert.deepEqual(sent.at(-1),expected({id:entry.id,color:'#123456'}),row.kind+' tint');
  await click(byText(slot,'Clear override'));assert.deepEqual(sent.at(-1),expected({id:entry.id}),row.kind+' clear tint');
  await click(byText(slot,'Clear'));assert.deepEqual(sent.at(-1),expected(null),row.kind+' default payload unchanged');
 }
});
await test('tint_is_sent_with_the_slot',async()=>{
 const {host,sent}=make(),slot=host.querySelector('[data-material-slot="Panes"]');
 await useMaterial(slot,entry.id);
 const tint=slot.querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');
 assert.deepEqual(sent.at(-1).material,{id:entry.id,color:'#123456'});
});
await test('read_only_shows_no_buttons',()=>{const {host}=make(true);assert.equal(host.querySelectorAll('button,input').length,0);});
await test('current_values_are_shown',()=>{
 const {host,building,plan}=make();building.materials.pane={id:entry.id};plan.materials.water={id:entry.id};host.replaceChildren();
 houseMaterialsShelf(host,building,{getPlan:()=>plan,getKit:()=>({}),library,canEdit:()=>false,op:()=>{throw Error('read only wrote');}});
 for(const label of ['Panes','Water'])assert.ok(textOf(host.querySelector(`[data-material-slot="${label}"]`)).includes('Family glass'));
});
await test('building_card_refreshes_house_and_site_values_and_read_only',async()=>{
 const {plan,building}=make();let writable=true;const sent=[];
 const cards=createCards({getPlan:()=>plan,getKit:()=>({}),getLabel:()=> 'House',library,canEdit:()=>writable,edit(){},op:async o=>sent.push(o),ask(){}});
 cards.draw({pieceId:'house',buildingId:'house'});const host=document.getElementById('piece-card');
 assert.ok(textOf(host).includes('House materials'));assert.ok(host.querySelector('[data-material-slot="Slab"]'));
 building.materials.pane={id:entry.id};plan.materials.water={id:entry.id};cards.draw();
 for(const label of ['Panes','Water'])assert.ok(textOf(host.querySelector(`[data-material-slot="${label}"]`)).includes('Family glass'));
 const slot=host.querySelector('[data-material-slot="Panes"]');await click(byText(slot,'Clear'));
 await cards.queue(async()=>{});assert.equal(sent.length,1);assert.equal(sent[0].material,null);
 writable=false;cards.draw();assert.equal(host.querySelector('[data-material-slot="Panes"]').querySelectorAll('button,input').length,0);
});
await test('grass_choice_on_every_real_household_building',async()=>{
 for(const building of input.household.buildings){
  const host=document.createElement('div'),sent=[];
  houseMaterialsShelf(host,building,{getPlan:()=>input.household,getKit:()=>({}),library,canEdit:()=>true,
   op:()=>{throw Error('grass changed the household plan')},settingsRequest:async(path,method,body)=>{
    if(method==='PUT')sent.push(body);return {lawn:{grass_type:'cool'}};
   }});
  await new Promise(r=>setTimeout(r,0));
  assert.ok(host.querySelector('[data-material-slot="Lawn"]'));
  const choice=host.querySelector('[name="lawn_grass_type"]');assert.equal(choice.value,'cool');
  choice.value='warm';await fire(choice,'change');await new Promise(r=>setTimeout(r,0));
  assert.deepEqual(sent,[{lawn_grass_type:'warm'}]);
 }
});
finish();
"""

if __name__ == '__main__':
    household = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'household': household})
    print(output)
    sys.exit(code or 0)
