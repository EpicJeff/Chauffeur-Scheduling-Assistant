"""Authoritative settle and deferred-yard runtime proof; no browser or WebGL."""
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_building_reuse_js import DRIVER as BUILDING_DRIVER

ROOT = Path(__file__).resolve().parents[1]
# Use the building-reuse rig, real generator, real yard and mounted view. Only
# observe generation/bake entry and optionally hold the yard's async completion.
PREFIX = BUILDING_DRIVER.split("await test(", 1)[0]
PREFIX = PREFIX.replace("return next(spec, ctx);", """
  if (spec === './twin_yard.js') return {url:data(`
    export * from '${file('static/twin/twin_yard.js')}';
    import {buildYard as build} from '${file('static/twin/twin_yard.js')}';
    export async function buildYard(...args) {
      const gate=globalThis.yardGate;globalThis.yardCalls++;
      if(gate) await gate;
      return build(...args);
    }`),shortCircuit:true};
  return next(spec, ctx);""")
PREFIX = PREFIX.replace("return url.startsWith('file:')", """
  if (url.endsWith('/twin_generator.js') || url.endsWith('/twin_view.js')) {
    const loaded=next(url,{...ctx,format:'module'});
    let source=String(loaded.source);
    source=source.replace(/(function generateTwin\\([^\\n]+\\{)\\r?\\n/, '$1\\n globalThis.generations++;\\n');
    source=source.replace('function startBake() {', 'function startBake() { globalThis.bakeStarts++;');
    source=source.replace('next.editableLevel = editableLevel;', 'next.editableLevel = editableLevel; globalThis.lastTwin = next;');
    return {...loaded,format:'module',source};
  }
  return url.startsWith('file:')""")
DRIVER = PREFIX + r"""
globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
const yard=v=>v.scene.getObjectByName('yard');
const hosts=new WeakMap();
const reset=()=>{globalThis.generations=0;globalThis.bakeStarts=0;globalThis.yardCalls=0;};
async function mount(plan=fixture(),editable='a:L1'){
 reset();location.search='?test=1';const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const v=await mountTwin(host,{plan,kit,tier:'low',bake:false});
 hosts.set(v,host);
 await v.setEditableLevel(editable);reset();return v;
}
const split=p=>{
 const b=p.buildings[0],old=b.walls.find(w=>w.id==='w1');
 b.walls=b.walls.filter(w=>w!==old);
 b.walls.push({...old,id:'w1a',to:[12,3]},{...old,id:'w1b',from:[12,3]});
};
await test('drag_preview_draws_on_unfocused_level',async()=>{
 const v=await mount(fixture(),null);try{
  assert.equal(lastTwin.editableLevel,null);
  const group=v.groups.levels['a:L1'],snapshots=[];
  group.traverse(o=>{for(const r of o.userData.snapRanges||[])snapshots.push({o,r,
   values:Array.from(o.geometry.attributes.position.array.slice(r.start*3,(r.start+r.count)*3))});});
  const owned=snapshots.filter(s=>s.r.pieceId==='w0');assert.ok(owned.length);
  assert.ok(owned.some(s=>s.o.userData.snapRanges.some(r=>r.pieceId!=='w0')),'exercise a shared batch');
  const p=structuredClone(v.plan);p.buildings[0].walls[0].from[1]++;p.buildings[0].walls[0].to[1]++;
  v.rebuildLevel('a','L1',p,{walls:['w0']});
  assert.equal(v.plan,p);assert.equal(v.groups.levels['a:L1'],group);assert.equal(generations,0);
  assert.equal(lastTwin.editableLevel,null);assert.equal(lastTwin.buildings.get('a').model.stale,true);
  for(const s of snapshots){
   const actual=Array.from(s.o.geometry.attributes.position.array.slice(s.r.start*3,(s.r.start+s.r.count)*3));
   if(s.r.pieceId==='w0'){
    const expected=s.values.map((n,i)=>i%3===2?n-1:n);assert.deepEqual(actual,expected);
   }else assert.deepEqual(actual,s.values,'other pieces must stay put');
  }
 }finally{v.dispose();}
});
await test('unfocused_keep_does_not_mark_building_stale',async()=>{
 const v=await mount(fixture(),null);try{
  const p=structuredClone(v.plan);p.buildings[0].walls[0].from[1]++;p.buildings[0].walls[0].to[1]++;
  v.rebuildLevel('a','L1',p,{walls:['w0']},{keep:true});
  assert.equal(v.plan,p);assert.ok(!lastTwin.buildings.get('a').model.stale);
  assert.equal(lastTwin.editableLevel,null);assert.equal(generations,0);
 }finally{v.dispose();}
});
await test('unfocused_batch_without_ranges_is_skipped',async()=>{
 const v=await mount(fixture(),null);try{
  const batches=[];v.groups.levels['a:L1'].traverse(o=>{
   if(o.userData.merged&&o.userData.snapRanges?.some(r=>r.pieceId==='w0')){
    batches.push({o,values:Array.from(o.geometry.attributes.position.array)});delete o.userData.snapRanges;
   }
  });assert.ok(batches.length);
  const p=structuredClone(v.plan);p.buildings[0].walls[0].from[1]++;p.buildings[0].walls[0].to[1]++;
  v.rebuildLevel('a','L1',p,{walls:['w0']});assert.equal(v.plan,p);
  for(const {o,values} of batches)assert.deepEqual(Array.from(o.geometry.attributes.position.array),values);
 }finally{v.dispose();}
});
await test('batched_room_drag_reuses_arrays_and_preserves_neighbours',async()=>{
 const plan=fixture();plan.buildings[0].rooms.push({id:'neighbour',level:'L1',polygon:square(20,0),state:'settled'});
 const v=await mount(plan,null);try{
  const group=v.groups.levels['a:L1'],snapshots=[];
  group.traverse(o=>{if(o.userData.snapRanges?.some(r=>r.pieceId==='room'))snapshots.push({o,geometry:o.geometry,
   arrays:Object.fromEntries(Object.entries(o.geometry.attributes).map(([name,a])=>[name,a.array])),
   neighbours:o.userData.snapRanges.filter(r=>r.pieceId!=='room').map(r=>({r,
    values:Object.fromEntries(Object.entries(o.geometry.attributes).map(([name,a])=>[name,
     Array.from(a.array.slice(r.start*a.itemSize,(r.start+r.count)*a.itemSize))]))}))});});
  assert.ok(snapshots.some(s=>s.neighbours.length),'exercise rooms sharing one batch');
  const old=v.worldBox('room','a');
  for(let frame=0;frame<2;frame++){
   const p=structuredClone(v.plan);p.buildings[0].rooms[0].polygon[1][0]++;
   v.rebuildLevel('a','L1',p,{rooms:['room']});assert.equal(v.plan,p);
   for(const s of snapshots){
    assert.equal(s.o.geometry,s.geometry);
    for(const [name,array] of Object.entries(s.arrays))assert.equal(s.o.geometry.attributes[name].array,array);
    for(const {r,values} of s.neighbours)for(const [name,expected] of Object.entries(values)){
     const a=s.o.geometry.attributes[name];
     assert.deepEqual(Array.from(a.array.slice(r.start*a.itemSize,(r.start+r.count)*a.itemSize)),expected);
    }
   }
  }
  assert.notDeepEqual(v.worldBox('room','a'),old);assert.equal(generations,0);
 }finally{v.dispose();}
});
await test('same_topology_deforms',async()=>{
 const v=await mount();try{
  const group=v.groups.levels['a:L1'],old=v.worldBox('room','a'),p=structuredClone(v.plan);
  p.buildings[0].rooms[0].polygon[1][0]=14;
  const result=await v.settle(p,{buildingId:'a',levelId:'L1',touched:{rooms:['room']}});
  assert.equal(result.path,'deform');assert.equal(generations,0);assert.equal(v.groups.levels['a:L1'],group);
  assert.notDeepEqual(v.worldBox('room','a'),old);assert.equal(v.plan,p);
 }finally{v.dispose();}
});
await test('split_rebuilds_and_keeps_selection',async()=>{
 const v=await mount();try{
  const p=structuredClone(v.plan);split(p);
  const selection={id:'w1',building:'a',kind:'wall'};
  const result=await v.settle(p,{buildingId:'a',levelId:'L1',selection});
  assert.equal(result.path,'rebuild');assert.equal(result.selection.id,'w1b');assert.equal(result.selection.building,'a');
  assert.ok(generations>0);assert.equal(v.plan,p);assert.ok(v.worldBox('w1b','a'));
 }finally{v.dispose();}
});
await test('yard_later_does_not_hold_ready',async()=>{
 const v=await mount();try{
  const old=yard(v),p=structuredClone(v.plan);split(p);p.site.fence=[{polyline:[[0,0],[10,0]],height:4}];
  globalThis.yardGate=new Promise(()=>{});
  const result=await Promise.race([v.rebuild(p,{yardLater:true}).then(()=>true),new Promise(r=>setTimeout(()=>r(false),250))]);
  assert.equal(result,true,'house ready must not wait for the yard');assert.equal(v.ready,true);
  assert.equal(yard(v),old);assert.ok(old.parent,'complete old yard stays attached');
 }finally{globalThis.yardGate=null;v.dispose();}
});
await test('bake_restarts_once',async()=>{
 for(const change of [p=>p.buildings[0].rooms[0].polygon[1][0]++,split]){
  const v=await mount();try{
   const p=structuredClone(v.plan);change(p);
   await v.settle(p,{buildingId:'a',levelId:'L1'});assert.equal(bakeStarts,1);
  }finally{v.dispose();}
 }
});
await test('unhinted_settle_deforms_every_changed_level',async()=>{
 const v=await mount();try{
  const groups=[v.groups.levels['a:L1'],v.groups.levels['b:L1']],p=structuredClone(v.plan);
  const before=p.buildings.map(b=>v.worldBox('room',b.id));
  for(const b of p.buildings)b.rooms[0].polygon[1][0]=15;
  const result=await v.settle(p);
  assert.equal(result.path,'deform');assert.equal(generations,0);assert.equal(bakeStarts,1);
  for(const [i,b] of p.buildings.entries()){
   assert.equal(v.groups.levels[b.id+':L1'],groups[i]);assert.notDeepEqual(v.worldBox('room',b.id),before[i]);
  }
  assert.equal(v.plan,p);
 }finally{v.dispose();}
});
await test('unhinted_topology_change_and_pieceId_selection',async()=>{
 const v=await mount();try{
  const p=structuredClone(v.plan);split(p);
  const result=await v.settle(p,{selection:{pieceId:'w1',buildingId:'a',kind:'wall'}});
  assert.equal(result.path,'rebuild');assert.equal(result.selection.pieceId,'w1b');
  assert.equal(result.selection.buildingId,'a');
 }finally{v.dispose();}
});
await test('yard_only_settle_preserves_buildings_and_reuses_yard_parts',async()=>{
 const initial=fixture();initial.site.hardscape=[{kind:'patio',polygon:square(16,0),material:'patio_concrete'}];
 const v=await mount(initial);try{
  const group=v.groups.levels['a:L1'],old=yard(v),p=structuredClone(v.plan);
  const retained=old.children.filter(o=>o.userData.yardPart==='hardscape');assert.ok(retained.length);
  p.site.fence=[{polyline:[[0,0],[10,0]],height:4}];
  const selection={id:'w1',building:'a',kind:'wall'},result=await v.settle(p,{selection});
  assert.equal(result.selection,selection);assert.equal(v.groups.levels['a:L1'],group);assert.equal(generations,0);
  // Yard is allowed to complete after the house/settle promise.
  for(let i=0;i<20&&yard(v)===old;i++)await new Promise(r=>setTimeout(r,5));
  assert.notEqual(yard(v),old);assert.equal(bakeStarts,1);assert.equal(v.plan,p);
  assert.ok(retained.every(o=>o.parent===yard(v)),'unchanged parts are adopted without rebuilding');
 }finally{v.dispose();}
});
await test('removed_wall_without_matching_segment_clears_selection',async()=>{
 const v=await mount();try{
  const p=structuredClone(v.plan);p.buildings[0].walls=p.buildings[0].walls.filter(w=>w.id!=='w1');
  const result=await v.settle(p,{selection:{id:'w1',building:'a',kind:'wall'}});assert.equal(result.selection,null);
 }finally{v.dispose();}
});
await test('hints_do_not_hide_server_room_corrections',async()=>{
 const v=await mount();try{
  const old=v.worldBox('room','a'),p=structuredClone(v.plan);p.buildings[0].rooms[0].polygon[1][0]=14;
  const result=await v.settle(p,{buildingId:'a',levelId:'L1',touched:{walls:['w1']}});
  assert.equal(result.path,'deform');assert.notDeepEqual(v.worldBox('room','a'),old);
 }finally{v.dispose();}
});
await test('batched_room_retriangulation_preserves_neighbours_and_draw_calls',async()=>{
 const plan=fixture();plan.buildings[1].rooms.push({id:'neighbour',level:'L1',polygon:square(20,0),state:'settled'});
 const v=await mount(plan);try{
  const group=v.groups.levels['b:L1'],before=[];
  const capture=()=>{const out=[];group.traverse(o=>{
   for(const r of o.userData.snapRanges||[])if(r.pieceId!=='room')out.push([o,r.pieceId,
    Array.from(o.geometry.attributes.position.array.slice(r.start*3,(r.start+r.count)*3))]);
  });return out;};
  before.push(...capture());assert.ok(before.length);
  const meshes=[];group.traverse(o=>{if(o.isMesh)meshes.push(o);});
  const p=structuredClone(v.plan);p.buildings[1].rooms[0].polygon=[[0,0],[14,0],[14,12],[7,14],[0,12]];
  await v.settle(p);assert.deepEqual(capture(),before);
  const after=[];group.traverse(o=>{if(o.isMesh)after.push(o);});assert.deepEqual(after,meshes);
  group.traverse(o=>{if(o.userData.snapRanges){assert.equal(o.geometry.index,null);assert.equal(o.geometry.attributes.position.count%3,0);}});
 }finally{v.dispose();}
});
await test('newer_rebuild_cancels_in_flight_yard_without_stealing_live_parts',async()=>{
 const v=await mount();let unblock;try{
  const p=structuredClone(v.plan);p.site.fence=[{polyline:[[0,0],[10,0]],height:4}];
  globalThis.yardGate=new Promise(r=>unblock=r);
  await v.rebuild(p,{yardLater:true});
  for(let i=0;i<20&&!yardCalls;i++)await new Promise(r=>setTimeout(r,5));
  assert.equal(yardCalls,1);const old=yard(v);assert.ok(old.parent);
  globalThis.yardGate=null;const newer=structuredClone(p);newer.site.fence[0].height=6;
  await v.rebuild(newer);const latest=yard(v);assert.notEqual(latest,old);
  let swaps=0;hosts.get(v).addEventListener('twinyardrebuilt',()=>swaps++);
  let disposed=0;latest.traverse(o=>o.geometry?.addEventListener('dispose',()=>disposed++));
  unblock();await new Promise(r=>setTimeout(r,40));
  assert.equal(yard(v),latest);assert.equal(v.plan,newer);assert.equal(disposed,0);assert.equal(swaps,0);
 }finally{globalThis.yardGate=null;unblock?.();v.dispose();}
});
await test('yard_failure_keeps_complete_previous_yard',async()=>{
 const v=await mount();let reject;try{
  const old=yard(v),p=structuredClone(v.plan);p.site.fence=[{polyline:[[0,0],[10,0]],height:4}];
  globalThis.yardGate=new Promise((_,r)=>reject=r);
  await v.rebuild(p,{yardLater:true});
  for(let i=0;i<20&&!yardCalls;i++)await new Promise(r=>setTimeout(r,5));
  reject(Error('yard unavailable'));await new Promise(r=>setTimeout(r,15));
  assert.equal(yard(v),old);assert.ok(old.parent);assert.equal(v.ready,true);
 }finally{globalThis.yardGate=null;v.dispose();}
});
await test('unchanged_host_records_follow_deformed_walls',async()=>{
 const v=await mount();try{
  const old=v.worldBox('door','a'),p=structuredClone(v.plan);p.buildings[0].walls[0].from[1]+=1;p.buildings[0].walls[0].to[1]+=1;
  await v.settle(p,{buildingId:'a',levelId:'L1',touched:{walls:['w0']}});
  assert.notDeepEqual(v.worldBox('door','a'),old);assert.equal(generations,0);
 }finally{v.dispose();}
});
await test('selection_midpoint_uses_point_zero_five_feet_and_same_level',async()=>{
 for(const offset of [.049,.051]){
  const v=await mount();try{
   const p=structuredClone(v.plan);split(p);const b=p.buildings[0];
   b.walls.find(w=>w.id==='w1b').from[0]+=offset;b.walls.find(w=>w.id==='w1b').to[0]+=offset;
   b.levels.push({id:'L2',elevation:8,ceiling:8,outline:square(0,0)});
   b.walls.unshift({id:'wrong-level',level:'L2',from:[12,0],to:[12,12],height:8,thickness:.5,state:'settled'});
   const result=await v.settle(p,{selection:{id:'w1',building:'a',kind:'wall'}});
   assert.equal(result.selection?.id??null,offset<.05?'w1b':null);
  }finally{v.dispose();}
 }
});
await test('deform_cancels_older_candidate_and_restores_ready',async()=>{
 const v=await mount();try{
  const pending=v.rebuild(v.plan),p=structuredClone(v.plan);p.buildings[0].rooms[0].polygon[1][0]=14;
  const result=await v.settle(p);await pending;
  assert.equal(result.path,'deform');assert.equal(v.ready,true);assert.equal(v.plan,p);assert.equal(bakeStarts,1);
 }finally{v.dispose();}
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=120)
    print(out)
    sys.exit(code or 0)
