"""Slice 7 rows execute their controls, resolver inheritance and plane targets."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
globalThis.fetch=async()=>new Response(JSON.stringify({materials:[],items:[]}));
const {materialSlot}=await import(file('static/twin/editor/material_slot.js'));
const {materialLines}=await import(file('static/twin/editor/library.js'));
const {houseMaterialsShelf}=await import(file('static/twin/editor/house_materials.js'));
const {drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {surfaceDescription}=await import(file('static/twin/editor/material_catalog.js'));
const library={selected:()=>({kind:'material',id:'oak',name:'Oak'}),onSelect:()=>()=>{},reveal:async()=>{}};
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
await test('inherited_tint_uv_wrap_rotation_reset_preserve_independent_fields',async()=>{
 const sent=[],node=materialSlot({label:'Floor',defaultLabel:'Oak',library,onChange:async ref=>sent.push(ref)});
 const tint=node.querySelector('input[type="color"]');assert.equal(tint.parentElement.hidden,false);
 tint.value='#123456';await fire(tint,'change');assert.deepEqual(sent.at(-1),{color:'#123456'});
 const u=node.querySelector('[data-slot-u]'),v=node.querySelector('[data-slot-v]'),rot=node.querySelector('[data-slot-rotation]');
 assert.ok(u&&v&&rot,'every material row has offset controls');assert.equal(u.step,'.05');
 u.value='1.05';await fire(u,'change');assert.deepEqual(sent.at(-1),{color:'#123456',uv:{u:.05,v:0,rot:0}});
 v.value='-.05';await fire(v,'change');rot.value='270';await fire(rot,'change');
 assert.deepEqual(sent.at(-1),{color:'#123456',uv:{u:.05,v:.95,rot:270}});
 await click(byText(node,'Clear override'));assert.deepEqual(sent.at(-1),{uv:{u:.05,v:.95,rot:270}});
 await click(byText(node,'Reset offset'));assert.equal(sent.at(-1),null);
 u.value='0';await fire(u,'change');assert.deepEqual(sent.at(-1),{uv:{u:0,v:0,rot:0}},'explicit zero persists');
 u.value='NaN';await fire(u,'change');assert.deepEqual(sent.at(-1),{uv:{u:0,v:0,rot:0}});
});
await test('inherited_offset_fields_show_the_resolved_uv_and_reset_only_the_local_uv',async()=>{
 const sent=[],uv={u:.25,v:.75,rot:90};
 const node=materialSlot({label:'Coping',defaultLabel:'Pool',library,
  resolve:ref=>surfaceDescription({materials:{pool_coping:{id:'oak',uv}}},{role:'pool_coping',ref}),onChange:async ref=>sent.push(ref)});
 const u=node.querySelector('[data-slot-u]'),v=node.querySelector('[data-slot-v]'),rot=node.querySelector('[data-slot-rotation]'),reset=node.querySelector('[data-slot-offset-reset]');
 assert.deepEqual([u.value,v.value,rot.value],['0.25','0.75','90']);assert.equal(reset.disabled,true);
 u.value='.3';await fire(u,'change');assert.deepEqual(sent.at(-1),{uv:{u:.3,v:.75,rot:90}});
 await click(reset);assert.equal(sent.at(-1),null);assert.equal(u.value,'0.25');
});
await test('room_rows_use_each_resolver_source_and_always_offer_walls',()=>{
 const room={id:'r',level:'l'},level={id:'l',materials:{}},building={id:'b',levels:[level],materials:{},rooms:[room]};
 const plan={buildings:[building],materials:{}},kit={materials:{floor:{asset:'oak'}}};
 const floor=()=>materialLines({kind:'room',piece:room,building},plan,kit)[0];
 assert.equal(floor().text,'House default: Oak');
 plan.materials.floor={id:'house'};assert.equal(floor().text,'House default: House');
 building.materials.floor={id:'building'};assert.equal(floor().text,'House default: Building');
 level.materials.floor={id:'level'};assert.equal(floor().text,'From this floor: Level');
 room.floor_material={uv:{u:0,v:0,rot:0}};assert.equal(floor().text,'From this floor: Level');
 room.floor_material={id:'own'};assert.equal(floor().text,'Own, set here');
 assert.deepEqual(materialLines({kind:'room',piece:room,building},plan,kit).map(r=>r.label),['Floor','Ceiling','Walls']);
});
await test('roof_planes_follow_generated_edges_and_rotation_relative_to_front',()=>{
 const roof={id:'roof',kind:'hip',rect:[0,0,10,10],plate:8,pitch:6,ridge:'x'},building={id:'b',levels:[],roof:{sections:[roof]}};
 const rows=()=>materialLines({kind:'roof',piece:roof,building},{buildings:[building]},{});
 assert.deepEqual(rows().map(r=>r.label),['Roof','Left slope','Right slope','Front slope','Back slope']);
 assert.deepEqual(rows().slice(1).map(r=>r.target),[{roof:'roof',plane:3},{roof:'roof',plane:1},{roof:'roof',plane:0},{roof:'roof',plane:2}]);
 roof.kind='gable';assert.deepEqual(rows().map(r=>r.label),['Roof','Front slope','Back slope']);
 building.rotation=90;assert.deepEqual(rows().map(r=>r.label),['Roof','Right slope','Left slope']);
 building.rotation=45;assert.deepEqual(rows().map(r=>r.label),['Roof','Slope 1','Slope 2']);
 roof.material={id:'oak'};assert.equal(rows()[1].text,'From the roof: Oak');
 roof.plane_materials={'0':{color:'#123456'}};assert.equal(rows()[1].current.color,'#123456');
});
await test('facing_room_item_colour_and_shared_texture_role_tints_match_the_renderer',()=>{
 const room={id:'room',name:'Kitchen',level:'l',polygon:[[-2,0],[12,0],[12,5],[-2,5]],wall_material:{id:'oak'}};
 const wall={id:'wall',level:'l',from:[0,0],to:[10,0],thickness:.5,exterior:true};
 const building={id:'b',levels:[{id:'l'}],walls:[wall],rooms:[room],materials:{cabinet:{id:'global'}}};
 const plan={buildings:[building],materials:{cabinet:{id:'house'}}};
 const rows=materialLines({kind:'wall',piece:wall,building},plan,{});
 assert.equal(rows.find(r=>r.label==='Kitchen').text,'From the room: Oak');
 const cabinet={id:'cabinet',kind:'counter',rect:[0,0,2,2],level:'l',body:'#123456'};
 const row=materialLines({kind:'fixture',piece:cabinet,building},plan,{}).find(r=>r.target.part==='cabinet');
 assert.equal(row.current.color,'#123456');assert.equal(row.text,'House default: Item colour #123456');
 const kit={materials:{retaining_block:{asset:'concrete',color:'#999999'},patio_concrete:{asset:'concrete',color:'#abcdef'}}};
 assert.equal(surfaceDescription({}, {role:'patio_concrete',ref:{id:'patio_concrete'}},kit).current.color,'#abcdef');
});
await test('ledge_and_steps_rows_send_feature_payload_and_honest_liner_default',async()=>{
 for(const kind of ['ledge','steps']){
  const piece={id:kind,kind,polygon:[[0,0],[4,0],[4,4],[0,4]]},pool={id:'pool',features:[piece],materials:{interior:{id:'blue'}}};
  const host=document.createElement('div'),sent=[];
  drawSiteShapeShelf(host,{kind,piece},{getPlan:()=>({site:{pool}}),library,canEdit:()=>true,queue:f=>Promise.resolve().then(f),
   op:async o=>sent.push(o),report:e=>{throw e;}});
  const rows=host.querySelectorAll('[data-library-slot]');assert.deepEqual(rows.map(r=>r.dataset.librarySlot),['Interior','Coping']);
  assert.match(textOf(rows[1].querySelector('[data-slot-name]')),/Pool liner: Blue/);
  for(const row of rows){await click(row.querySelector('[data-slot-use]'));await new Promise(r=>setTimeout(r,0));
   assert.deepEqual(sent.at(-1),{op:'update_pool_feature',id:kind,materials:{[row.dataset.librarySlot.toLowerCase()]:{id:'oak'}}});}
 }
});
finish();
"""
if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code)
