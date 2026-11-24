"""Task 1: run the real Move to destination/operation modules under node.

Run from chauffeur/: python tests/test_twin_move_to_js.py. No browser or HA.
"""
from pathlib import Path

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]

DRIVER = PRELUDE + r"""
const {moveTargets, moveOps} = await import(file('static/twin/editor/move_to.js'));
const {toLot, toLocal, hostedAt} = await import(file('static/twin/editor/lot_frame.js'));
const {hostPoint} = await import(file('static/twin/twin_hosts.js'));
const {groundAt, buildingBase} = await import(file('static/twin/twin_ground.js'));
const near = (a,b) => assert.ok(Math.abs(a-b)<1e-6, `${a} near ${b}`);
const xyNear = (a,b) => {assert.equal(a.length,2); for(let i=0;i<2;i++)near(a[i],b[i]);};
const ref = (kind,pieceId,buildingId) => ({kind,pieceId,...(buildingId?{buildingId}:{})});
const chair = ref('item','chair','house');
const polygon = (x0,y0,x1,y1) => [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
function fixture() {
 return {site:{lot:polygon(-100,-100,100,100),furniture:[],planting:[{id:'tree',asset:'oak',at:[0,0]}],
  terraces:[{id:'pad',polygon:polygon(-50,-50,50,50),height:4,blend:0}]},buildings:[
  {id:'house',name:'House',position:[20,10],rotation:30,base:7,
   levels:[{id:'lower',name:'Ground floor',elevation:0,ceiling:8},{id:'upper',name:'Upper floor',elevation:10,ceiling:9}],
   rooms:[{id:'lower-room',level:'lower',polygon:polygon(0,0,10,10)},
    {id:'upper-room',level:'upper',polygon:polygon(0,0,10,10),floor_offset_ft:1}],
   walls:[],roofs:[],items:[{id:'chair',asset:'chair',host:{floor:'upper-room',u:.2,v:.4},rotation:10,elevation:2.5,
    tint:'#123456',scale:1.2,scale_axes:[1,2,3],casts_shadow:false,object_kind:'lamp',light_entity:'light.chair',
    emissive:2,mirror_x:true,mirror_y:false,visible_in:['editor'],src:{person:true},state:'settled',device:'old',device_id:'old'}]},
  {id:'pool-house',name:'Pool house',position:[30,20],rotation:-25,base:12,
   levels:[{id:'ground',name:'Ground floor',elevation:0,ceiling:8}],
   rooms:[{id:'pool-room',level:'ground',polygon:polygon(-50,-50,50,50),floor_offset_ft:-1}],walls:[],roofs:[],items:[]}
 ]};
}
function unchanged(plan, fn) {const before=structuredClone(plan), out=fn();assert.deepEqual(plan,before,'pure module must not mutate plan');return out;}
function carried(source, op) {
 for(const field of ['asset','elevation','tint','scale','scale_axes','casts_shadow','object_kind','light_entity','emissive','mirror_x','mirror_y','visible_in'])
  assert.deepEqual(op[field],source[field],field);
 for(const field of ['src','state','device','device_id'])assert.equal(field in op,false,field+' is stripped');
 assert.equal(op.id,source.id);
}
await test('test_targets_list_site_and_every_level',()=>{
 const p=fixture(), targets=unchanged(p,()=>moveTargets(p,[chair]));
 assert.deepEqual(targets,[{key:'site',label:'Site',disabled:false},
  {key:'house:lower',label:'House · Ground floor',disabled:false},
  {key:'pool-house:ground',label:'Pool house · Ground floor',disabled:false}]);
 assert.deepEqual(moveTargets(p,[chair,ref('furniture','outside')]).map(t=>t.key),['site','house:lower','house:upper','pool-house:ground']);
 p.site.furniture=[{id:'outside',asset:'chair',at:[20,20]}];
 assert.ok(!moveTargets(p,[ref('furniture','outside')]).some(t=>t.key==='site'));
 const other={...structuredClone(p.buildings[0].items[0]),id:'other'};p.buildings[0].items.push(other);
 assert.ok(!moveTargets(p,[chair,ref('item','other','house')]).some(t=>t.key==='house:upper'));
 assert.deepEqual(moveTargets(p,[]),[]);
});
await test('test_building_to_site_keeps_spot_facing_height',()=>{
 const p=fixture(), b=p.buildings[0], item=b.items[0], point=hostPoint(b,item.host);
 assert.equal(point[2],11,'upper floor plus raised floor');assert.equal(buildingBase(p,b),7);
 const result=unchanged(p,()=>moveOps(p,[chair],'site'));
 assert.deepEqual(result.ops.map(o=>o.op),['delete','add_site_item']);
 assert.deepEqual(result.ops[0],{op:'delete',building:'house',id:'chair'});
 const op=result.ops[1], angle=Math.PI/6;
 xyNear(op.at,[20+2*Math.cos(angle)-4*Math.sin(angle),10+2*Math.sin(angle)+4*Math.cos(angle)]);
 xyNear(op.at,toLot(b,point.slice(0,2)));assert.equal(op.rotation,40);
 assert.equal(groundAt(p,...op.at),4);assert.equal(op.elevation,2.5,'offset above new ground, not absolute upper-floor height');
 assert.equal(op.list,'furniture');assert.equal(op.require_inside,true);assert.ok(!('host' in op));carried(item,op);
 assert.deepEqual(result.selection,[ref('furniture','chair')]);
 // Outputs must not alias the source property records.
 op.scale_axes[0]=99;assert.equal(item.scale_axes[0],1);
});
await test('test_site_to_building_lands_in_room',()=>{
 const p=fixture(), b=p.buildings[0], item=b.items[0];
 p.site.furniture=[{...structuredClone(item),at:toLot(b,[2,4]),rotation:10}];b.items=[];
 const result=unchanged(p,()=>moveOps(p,[ref('furniture','chair')],'house:upper'));
 assert.deepEqual(result.ops.map(o=>o.op),['delete_site_item','add_item']);
 assert.deepEqual(result.ops[0],{op:'delete_site_item',list:'furniture',id:'chair'});
 const op=result.ops[1];assert.equal(op.building,'house');assert.equal(op.host.floor,'upper-room');
 xyNear(hostPoint(b,op.host).slice(0,2),[2,4]);assert.equal(op.rotation,340);assert.ok(!('at' in op));carried(item,op);
 assert.deepEqual(result.selection,[chair]);
});
await test('test_level_change_same_building_is_move_hosted',()=>{
 const p=fixture(), item=p.buildings[0].items[0];item.host={ceiling:'upper-room',u:.2,v:.4};item.offset=1.25;
 const result=unchanged(p,()=>moveOps(p,[chair],'house:lower'));
 assert.deepEqual(result,{ops:[{op:'move_hosted',building:'house',id:'chair',host:{ceiling:'lower-room',u:.2,v:.4}}],selection:[chair]});
 assert.equal(item.offset,1.25,'same-owner move retains its existing hosted offset');
});
await test('floor_offset_folds_into_elevation_to_site',()=>{
 for(const offset of [1.25,-.75])for(const elevation of [2.5,undefined]) {
  const p=fixture(), b=p.buildings[0], item=b.items[0];item.offset=offset;
  if(elevation===undefined)delete item.elevation;
  const oldRelative=hostPoint(b,item.host,item.offset)[2]-hostPoint(b,item.host)[2]+(item.elevation||0);
  const result=unchanged(p,()=>moveOps(p,[chair],'site')), op=result.ops[1];
  assert.deepEqual(result.ops.map(o=>o.op),['delete','add_site_item']);
  near(op.elevation,oldRelative);assert.equal('offset' in op,false,'add_site_item ignores offset; fold it once');
  xyNear(op.at,toLot(b,hostPoint(b,item.host,item.offset).slice(0,2)));assert.equal(op.rotation,40);
  assert.equal(op.id,item.id);assert.deepEqual(result.selection,[ref('furniture','chair')]);
 }
});
for(const ceiling of [false,true])await test(`${ceiling?'ceiling':'floor'}_offset_folds_into_elevation_to_other_building`,()=>{
 for(const offset of [1.25,-.75])for(const elevation of [2.5,undefined]) {
  const p=fixture(), [a,b]=p.buildings, item=a.items[0];item.offset=offset;
  if(elevation===undefined)delete item.elevation;
  if(ceiling)item.host={ceiling:'upper-room',u:.2,v:.4};
  const oldRelative=hostPoint(a,item.host,item.offset)[2]-hostPoint(a,item.host)[2]+(item.elevation||0);
  const result=unchanged(p,()=>moveOps(p,[chair],'pool-house:ground')), op=result.ops[1];
  assert.deepEqual(result.ops.map(o=>o.op),['delete','add_item']);
  assert.equal(op.host[ceiling?'ceiling':'floor'],'pool-room');assert.equal(op.id,item.id);
  // Reconstruct what add_item accepts: offset is not an object-schema field.
  const renderedRelative=hostPoint(b,op.host)[2]+(op.elevation||0)-hostPoint(b,op.host)[2];
  near(renderedRelative,oldRelative);assert.equal('offset' in op,false,'fold the signed offset once');
  xyNear(toLot(b,hostPoint(b,op.host).slice(0,2)),toLot(a,hostPoint(a,item.host,item.offset).slice(0,2)));
  assert.equal(op.rotation,65);assert.deepEqual(result.selection,[ref('item','chair',b.id)]);
 }
});
await test('cross_building_preserves_world_point_facing_and_ceiling',()=>{
 for(const ceiling of [false,true]) {
  const p=fixture(), [a,b]=p.buildings,item=a.items[0];if(ceiling)item.host={ceiling:'upper-room',u:.2,v:.4};
  const oldLot=toLot(a,hostPoint(a,item.host).slice(0,2));
  const result=unchanged(p,()=>moveOps(p,[chair],'pool-house:ground'));
  assert.deepEqual(result.ops.map(o=>o.op),['delete','add_item']);const op=result.ops[1];
  assert.equal(op.building,b.id);assert.equal(op.host[ceiling?'ceiling':'floor'],'pool-room');
  xyNear(toLot(b,hostPoint(b,op.host).slice(0,2)),oldLot);assert.equal(op.rotation,65);carried(item,op);
  assert.deepEqual(result.selection,[ref('item','chair',b.id)]);
 }
});
await test('rotated_round_trip_keeps_world_frame',()=>{
 const p=fixture(), b=p.buildings[0], original=b.items[0];
 const out=moveOps(p,[chair],'site').ops[1];
 p.site.furniture=[{...out}];b.items=[];
 const back=moveOps(p,[ref('furniture','chair')],'house:upper').ops[1];
 xyNear(hostPoint(b,back.host).slice(0,2),[2,4]);near(back.rotation,original.rotation);carried(original,back);
});
await test('test_refusals_all_or_nothing',()=>{
 const p=fixture(), b=p.buildings[0];b.items.push({...structuredClone(b.items[0]),id:'blocked',host:{floor:'upper-room',u:.9,v:.9}});
 b.rooms[0].polygon=polygon(0,0,5,5);const blocked=ref('item','blocked','house');
 assert.deepEqual(unchanged(p,()=>moveOps(p,[chair,blocked],'house:lower')),
  {refused:[{ref:blocked,reason:'No room under it on Ground floor.'}]});
});
await test('hostedAt_failure_is_an_atomic_no_room_refusal',()=>{
 const p=fixture(), b=p.buildings[0], blocked=ref('item','blocked','house');
 b.items.push({...structuredClone(b.items[0]),id:'blocked',host:{floor:'upper-room',u:.9,v:.9}});
 // Force an inconsistent room lookup through the real helpers: roomAt finds
 // the destination level, but hostedAt finds an earlier same-id stale room.
 b.rooms.unshift({id:'lower-room',level:'stale-level',polygon:polygon(0,0,5,5)});
 assert.throws(()=>hostedAt(b,{floor:'lower-room'},[9,9]),/copied piece does not fit/);
 assert.deepEqual(unchanged(p,()=>moveOps(p,[chair,blocked],'house:lower')),
  {refused:[{ref:blocked,reason:'No room under it on Ground floor.'}]});
});
await test('wall_and_roof_disable_targets_and_refuse_entire_selection',()=>{
 for(const host of [{wall:'wall',at:2,z:3},{roof:'roof',edge:0,at:2}]) {
  const p=fixture(), b=p.buildings[0], blocked=ref('item','blocked','house');
  b.items.push({id:'blocked',host});
  const reason='Wall and roof pieces stay on their wall or roof.';
  const targets=moveTargets(p,[chair,blocked]);assert.ok(targets.length);
  assert.ok(targets.every(t=>t.disabled===true&&t.reason===reason));
  assert.deepEqual(unchanged(p,()=>moveOps(p,[chair,blocked],'site')),{refused:[{ref:blocked,reason}]});
 }
});
await test('plant_and_ceiling_to_site_refuse_with_exact_reasons',()=>{
 const p=fixture(), plant=ref('planting','tree');
 assert.deepEqual(moveOps(p,[chair,plant],'house:lower'),{refused:[{ref:plant,reason:'Plants stay on the site.'}]});
 p.buildings[0].items.push({id:'ceiling',asset:'lamp',host:{ceiling:'upper-room',u:.3,v:.3}});
 const ceiling=ref('item','ceiling','house');
 assert.deepEqual(moveOps(p,[chair,ceiling],'site'),{refused:[{ref:ceiling,reason:'Ceiling pieces cannot go to the site.'}]});
});
await test('outside_lot_is_atomic_but_missing_lot_is_allowed',()=>{
 const p=fixture(), b=p.buildings[0], blocked=ref('item','blocked','house');
 b.items.push({...structuredClone(b.items[0]),id:'blocked',host:{ground:true,at:[300,300]}});
 assert.deepEqual(unchanged(p,()=>moveOps(p,[chair,blocked],'site')),{refused:[{ref:blocked,reason:'Outside the lot.'}]});
 delete p.site.lot;assert.equal(moveOps(p,[chair,blocked],'site').ops.length,4);
});
await test('mixed_current_places_skip_noop_and_keep_selection_order',()=>{
 const p=fixture(), b=p.buildings[0], other=ref('item','other','house');
 b.items.push({...structuredClone(b.items[0]),id:'other',host:{floor:'lower-room',u:.6,v:.6}});
 const result=unchanged(p,()=>moveOps(p,[other,chair],'house:lower'));
 assert.equal(result.ops.length,1);assert.equal(result.ops[0].id,'chair');assert.deepEqual(result.selection,[other,chair]);
 assert.deepEqual(moveOps(p,[chair],'house:upper'),{ops:[],selection:[chair]});
 assert.deepEqual(moveOps(p,[],'site'),{ops:[],selection:[]});
});
await test('multi_selection_emits_one_flat_batch_with_delete_before_add',()=>{
 const p=fixture(), b=p.buildings[0], other=ref('item','other','house');
 b.items.push({...structuredClone(b.items[0]),id:'other',host:{floor:'upper-room',u:.6,v:.6}});
 const result=moveOps(p,[chair,other],'site');
 assert.deepEqual(result.ops.map(o=>o.op),['delete','add_site_item','delete','add_site_item']);
 assert.deepEqual(result.selection,[ref('furniture','chair'),ref('furniture','other')]);
 assert.ok(result.ops.filter(o=>o.op==='add_site_item').every(o=>o.require_inside));
});
await test('devices_openings_and_lights_are_not_movable',()=>{
 const p=fixture();for(const kind of ['device','opening','light','light_fixture','effect_fixture','anchor']) {
  const blocked=ref(kind,kind,'house'),result=moveOps(p,[chair,blocked],'site');
  assert.equal(result.refused.length,1);assert.deepEqual(result.refused[0].ref,blocked);assert.ok(result.refused[0].reason);
  assert.ok(!('ops' in result));
 }
});
await test('lot_helpers_preserve_clipboard_3d_and_host_behaviour',()=>{
 const p=fixture(), b=p.buildings[0];
 xyNear(toLocal(b,toLot(b,[2,4])),[2,4]);
 const q=toLocal({...b,position:[20,10,7]},toLot({...b,position:[20,10,7]},[2,4,11]));
 for(let i=0;i<3;i++)near(q[i],[2,4,11][i]);
 assert.deepEqual(hostedAt(b,{ground:true,at:[0,0]},[2,4,9]),{ground:true,at:[2,4]});
 b.walls=[{id:'wall',from:[0,0],to:[10,0]}];b.roofs=[{id:'roof',area:polygon(0,0,10,10)}];
 assert.deepEqual(hostedAt(b,{wall:'wall',side:'left',z:3},[2,4]),{wall:'wall',side:'left',z:3,at:2});
 assert.deepEqual(hostedAt(b,{roof:'roof',edge:1,z:3},[2,4]),{roof:'roof',edge:1,z:3,at:4});
 assert.throws(()=>hostedAt(b,{floor:'upper-room'},[20,20]),/copied piece does not fit/);
});
finish();
"""


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    assert code == 0, output


if __name__ == '__main__':
    main()
