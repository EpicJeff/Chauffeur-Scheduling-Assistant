"""Picker cycling and real mounted-view raycasts under Node (no browser)."""
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {createPicker,DRAG_THRESHOLD_PX,HANDLE_HIT_PX,CYCLE_SLOP_PX}=await import(file('static/twin/editor/picking.js'));
const tree={kind:'tree',id:'tree',distance:4},house={kind:'building',id:'house',building:'house',distance:9};
const picker=options=>createPicker({sources:[()=>[house],()=>[tree]],...options});
await test('threshold_constants',()=>{
 assert.equal(DRAG_THRESHOLD_PX,3);assert.equal(HANDLE_HIT_PX,16);assert.equal(CYCLE_SLOP_PX,4);
});
await test('nearest_first_across_sources',()=>{
 const p=picker();assert.deepEqual(p.at(20,30),[tree,house]);assert.equal(p.click(20,30),tree);
});
await test('second_click_cycles',()=>{
 const p=picker();assert.equal(p.click(20,30),tree);assert.equal(p.click(20,30),house);assert.equal(p.click(20,30),tree);
});
await test('moved_click_does_not_cycle',()=>{
 const p=picker();assert.equal(p.click(20,30),tree);assert.equal(p.click(26,30),tree);
});
await test('cycle_restarts_when_hits_change',()=>{
 let hits=[tree,house];const p=createPicker({sources:[()=>hits]});assert.equal(p.click(20,30),tree);
 const other={kind:'tree',id:'other',distance:2};hits=[other,house];assert.equal(p.click(20,30),other);
});
await test('peek_matches_click_without_advancing',()=>{
 const p=picker();assert.equal(p.peek(20,30),tree);assert.equal(p.peek(20,30),tree);assert.equal(p.click(20,30),tree);
 assert.equal(p.peek(20,30),house);assert.equal(p.peek(20,30),house);assert.equal(p.click(20,30),house);
});
await test('unpickable_skipped',()=>{
 const p=picker({isPickable:c=>c.kind!=='tree'});assert.deepEqual(p.at(20,30),[house]);assert.equal(p.click(20,30),house);
});
await test('dedupe_keeps_nearest_and_ties_keep_source_order',()=>{
 const far={kind:'item',building:'a',id:'same',distance:8},near={...far,distance:4,part:'front'};
 const otherBuilding={...near,building:'b'},otherKind={...near,kind:'fixture'},site={...near,building:null};
 const p=createPicker({sources:[()=>[far,tree],()=>[near,otherBuilding,otherKind,site,{...site,building:undefined}]]});
 assert.deepEqual(p.at(0,0),[tree,near,otherBuilding,otherKind,site]);
 const filtered=createPicker({sources:[()=>[near,far]],isPickable:c=>c!==near});assert.deepEqual(filtered.at(0,0),[far]);
});
await test('slop_is_screen_distance_from_previous_click',()=>{
 const p=picker();p.click(0,0);assert.equal(p.click(4,0),house);assert.equal(p.click(8,0),tree);
 assert.equal(p.click(11,3),tree,'diagonal outside a 4px radius restarts');
});
await test('same_keys_after_rebuild_cycle_but_new_order_restarts',()=>{
 let hits=[tree,house];const p=createPicker({sources:[()=>hits]});p.click(0,0);
 hits=hits.map(c=>({...c}));assert.equal(p.click(0,0),hits[1]);
 hits=[{...house,distance:2},tree];assert.equal(p.click(0,0),hits[0]);
});
await test('at_and_peek_do_not_remember_and_reset_forgets',()=>{
 const p=picker();p.click(0,0);p.at(50,50);p.peek(50,50);assert.equal(p.click(0,0),house);
 p.reset();assert.equal(p.click(0,0),tree);
 const empty=createPicker({sources:[()=>[]]});assert.deepEqual(empty.at(0,0),[]);assert.equal(empty.peek(0,0),null);assert.equal(empty.click(0,0),null);
});

const T=await import('three');
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const FT=.3048,square=[[0,0],[10,0],[10,10],[0,10]],kit={materials:{}};
const fixture=()=>({buildings:[{id:'pick',position:[0,0],levels:[{id:'L1',elevation:0,ceiling:8,outline:square}],
 walls:[{id:'wall',level:'L1',from:[0,0],to:[10,0],height:8,thickness:.5,exterior:true,state:'settled'}],
 rooms:[{id:'room',level:'L1',polygon:square,state:'settled'}],openings:[],anchors:[],items:[],roof:{sections:[]}}],site:{},materials:{}});
async function mount(plan=fixture()){
 const host=new Element(),shell=new Element();shell.className='editor-shell';shell.append(host);
 const v=await mountTwin(host,{plan,kit,tier:'low',bake:false,preserveCamera:true});
 while(!v.ready)await new Promise(r=>setTimeout(r,1));
 v.setView('ext');v.setCameraState({position:[5*FT,12*FT,10*FT],target:[5*FT,0,-5*FT]});return v;
}
await test('pick_all_lists_stacked_pieces',async()=>{
 const v=await mount();try{
  const pixel=v.screenOfFloor(5,5,'pick:L1'),hits=v.pickAll(...pixel);
  assert.equal(hits[0].id,'wall');assert.ok(hits.some(h=>h.id==='room'),'floor behind wall is retained');
  assert.equal(new Set(hits.map(h=>JSON.stringify([h.building,h.id]))).size,hits.length);
  assert.ok(hits.every((h,i)=>Number.isFinite(h.distance)&&h.distance>0&&(!i||h.distance>=hits[i-1].distance)));
  assert.deepEqual(hits[0],{kind:'wall',id:'wall',building:'pick',pieceId:'wall',buildingId:'pick',level:'L1',distance:hits[0].distance,part:hits[0].part,point:hits[0].point});
  assert.ok(Math.abs(new T.Vector3(...hits[0].point).distanceTo(v.camera.position)-hits[0].distance)<1e-6,'ray distance is in metres');
  const chosen=v.pick(...pixel);assert.equal(chosen.kind,'wall');assert.equal(chosen.id,'wall');assert.equal(chosen.building,'pick');assert.equal(chosen.level,'L1');
  assert.equal('distance' in chosen,false,'legacy pick shape is unchanged');
  assert.ok(v.pickAll(...pixel,{skip:['wall']}).every(h=>h.kind!=='wall'));
  assert.equal(v.pick(...pixel,{skip:['wall']})?.id,'room');
  assert.deepEqual(v.pickAll(-1,450),[]);assert.deepEqual(v.pickAll(1440,450),[]);assert.deepEqual(v.pickAll(720,900),[]);
 }finally{v.dispose();}
});
await test('pick_all_shares_hidden_and_focused_room_filters',async()=>{
 const v=await mount();try{
  const pixel=v.screenOfFloor(5,5,'pick:L1');
  v.setSelection({selected:{kind:'room',id:'room',building:'pick',level:'L1'},room:{id:'room',building:'pick',level:'L1',allowed:['room'],walls:[]}});
  assert.deepEqual(v.pickAll(...pixel).map(h=>h.id),['room']);assert.equal(v.pick(...pixel)?.id,'room');
  v.groups.levels['pick:L1'].visible=false;assert.deepEqual(v.pickAll(...pixel),[]);assert.equal(v.pick(...pixel),null);
 }finally{v.dispose();}
});
await test('pick_all_keeps_distance_order_and_pick_keeps_plan_wall_preference',async()=>{
 const plan=fixture();plan.buildings[0].levels.push({id:'L2',elevation:12,ceiling:8,outline:square});
 plan.buildings[0].rooms.push({id:'upper',level:'L2',polygon:square,state:'settled'});
 plan.buildings[0].roof.sections=[{id:'roof',kind:'gable',rect:[0,0,10,10],plate:20,pitch:6,ridge:'x',overhang:1}];
 const v=await mount(plan);try{
  v.setView('ext');v.setPlanCamera('pick:L1');const pixel=v.screenOfFloor(5,.1,'pick:L1'),hits=v.pickAll(...pixel);
  assert.ok(hits.some(h=>h.id==='upper'));assert.ok(hits.every(h=>h.kind!=='roof'));
  assert.equal(hits[0].id,'upper','nearest upper floor precedes wall');assert.equal(v.pick(...pixel)?.id,'wall');
  v.setView('pick:L1');assert.ok(v.pickAll(...pixel).every(h=>h.level==='L1'));
 }finally{v.dispose();}
});
await test('pick_all_does_not_apply_hosted_piece_preference',async()=>{
 const plan=fixture();plan.buildings[0].openings=[{id:'door',wall:'wall',level:'L1',kind:'door',at:3.5,width:3,sill:0,head:7,state:'settled'}];
 const v=await mount(plan);try{
  const pixel=v.screenOfFloor(5,5,'pick:L1'),hits=v.pickAll(...pixel);
  assert.ok(hits.some(h=>h.id==='door'));assert.equal(hits[0].id,'wall');assert.equal(v.pick(...pixel)?.id,'door');
 }finally{v.dispose();}
});
await test('pick_all_water_is_opt_in',async()=>{
 const plan={buildings:[],materials:{},site:{pool:{id:'pool',polygon:square,depth:4,coping:1,elevation:0}}};
 const v=await mount(plan);try{
  v.setCameraState({position:[5*FT,20*FT,-4.999*FT],target:[5*FT,0,-5*FT]});
  assert.deepEqual(v.pickAll(720,450),[]);assert.equal(v.pick(720,450),null);
  const hits=v.pickAll(720,450,{water:true});assert.equal(hits.length,1);assert.equal(hits[0].kind,'pool');
  assert.equal(hits[0].id,v.pick(720,450,{water:true}).id);assert.equal(hits[0].building,null);assert.equal(hits[0].level,null);
 }finally{v.dispose();}
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    sys.exit(code or 0)
