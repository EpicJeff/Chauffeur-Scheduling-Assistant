"""Real mounted view/yard under Node; renderer and external tree generator doubled."""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '\n'.join(line for line in PRELUDE.splitlines() if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url:data(`import {Group} from '${three}'; export class Tree extends Group { constructor(){super();this.options={};} loadPreset(){} generate(){ globalThis.__plantGenerations=(globalThis.__plantGenerations||0)+1; this.clear?.(); this.add(new (globalThis.__THREE_MESH)(new (globalThis.__THREE_BOX)(1,2,1), new (globalThis.__THREE_STD)())); } }`),shortCircuit:true};
  if (spec === 'three')""")

DRIVER = PREFIX + r"""
const THREE = await import('three');
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {yardKey,yardMaterialKey,buildYard,canonicalOutline,yardPartKeys,YARD_PARTS} = await import(file('static/twin/twin_yard.js'));
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
const {beginEdit,mountEditTiming} = await import(file('static/twin/edit_timing.js'));
const {rememberImport,forgetImport} = await import(file('static/twin/twin_library.js'));
const square=(x,y,w=4)=>[[x,y],[x+w,y],[x+w,y+w],[x,y+w]];
const fixture=()=>{
 const plan=structuredClone(input.plan);
 plan.buildings[0].rotation=0;
 plan.buildings[0].levels[0].outline=square(0,0,12);
 plan.buildings[0].levels[1].outline=square(0,0,6);
 plan.site={lot:square(-2,-2,8),terraces:[{polygon:square(0,0),height:2,blend:3,
   edges:[{edge:'sharp',wall:{material:'stone',thickness_in:8,above_in:1,materials:{face:{id:'wall-slot',color:'#334455'}}}}]}],
   fence:[{polyline:[[0,0],[2,0]],height:3,elevation:0,materials:{boards:{id:'boards-slot'},posts:{id:'post-slot'},rails:{id:'rail-slot'}}}],
   hardscape:[{kind:'path',points:[[0,0],[2,0]],width:1,corner:'rounded',smooth:false,radius:1,edging:'curb',elevation:0,material:'paving',materials:{surface:{id:'surface-slot'},edging:{id:'curb-slot'}}}],
   pool:{polygon:square(5,5,2),depth:4,coping:1,elevation:0,material:'paving',materials:{coping:{id:'coping-slot'},interior:{id:'inside-slot'}}},
   beds:[{polygon:square(0,0,1),elevation:0,material:'mulch',materials:{fill:{id:'fill-slot'}}}],
   edges:[{polygon:square(0,0,1),elevation:0,material:'lawn',materials:{strip:{id:'strip-slot'}}}],
   fire_pit:[{id:'fire',at:[1,1],shape:'round',radius:1,rotation:0,fuel:'gas',body:'stone',top:'granite',height_in:18,glass:'blue',entity:'light.fire',elevation:0,materials:{body:{id:'body-slot'},top:{id:'top-slot'}}}],
   planting:[],furniture:[]};
 return plan;
};
async function mount(plan,editor=true,tier='high',kit={materials:{}}) {
 location.search='?test=1';
 const host=new Element();
 if(editor){const shell=new Element();shell.className='editor-shell';shell.append(host);}
 return mountTwin(host,{plan:structuredClone(plan),kit,tier,bake:false});
}
const yard=v=>v.scene.getObjectByName('yard');
const {groundAt} = await import(file('static/twin/twin_ground.js'));
const {disposeObject} = await import(file('static/twin/twin_library.js'));
const planted=()=>({buildings:[],materials:{},site:{
 terraces:[{polygon:square(0,0,10),height:3,blend:4}],
 planting:[
  {id:'a',preset:'oak',at:[20,20],height:12,seed:1},
  {id:'b',preset:'pine',at:[2,2],height:9,seed:2,scale:1.2,scale_axes:[.8,1.3,1.1],pitch:4,rotation:25,roll:3,tint:'#789abc'},
  {id:'c',preset:'birch',at:[4,4],height:7,seed:3,casts_shadow:false}
 ]}});
const plantObjects=g=>g.children.filter(o=>o.userData.yardPart==='plants');
const plantSnapshot=g=>plantObjects(g).map(plant=>{
 const meshes=[];plant.traverse(o=>{if(o.isMesh)meshes.push({
  position:o.position.toArray(),rotation:o.rotation.toArray(),scale:o.scale.toArray(),
  vertices:Array.from(o.geometry.attributes.position.array),castShadow:o.castShadow,receiveShadow:o.receiveShadow,
  materials:[].concat(o.material).map(m=>({name:m.name,color:m.color?.getHex(),roughness:m.roughness,
   side:m.side,alphaTest:m.alphaTest,opacity:m.opacity,emissive:m.emissive?.getHex(),userData:m.userData}))
 });});
 return {name:plant.name,position:plant.position.toArray(),rotation:plant.rotation.toArray(),scale:plant.scale.toArray(),meshes};
});
const buildPlants=(p,previous=null,tier='high',viewing=false)=>buildYard(p,{materials:{}},tier,
 {previous,viewing,materials:previous?new Map(previous.userData.materials):null});
await test('moving_one_plant_generates_no_trees',async()=>{
 const plan=planted(),first=(await buildPlants(plan)).group,before=plantObjects(first);
 assert.equal(before.length,3);const oldPosition=before[0].position.clone();
 plan.site.planting[0].at=[2,3];globalThis.__plantGenerations=0;
 const next=(await buildPlants(plan,first)).group;
 assert.equal(globalThis.__plantGenerations,0,'moving runs neither presetTree nor bakePreset');
 assert.equal(before[0].parent,first,'preparation must not steal the live plant');
 assert.deepEqual(before[0].position,oldPosition,'preparation must not move the live plant');
 next.userData.adoptParts();
 assert.deepEqual(plantObjects(next),before,'all three exact objects survive');
 assert.deepEqual(before[0].position.toArray(),[2,groundAt(plan,2,3)+6,-3],'new grade plus the preset base offset');
 let releases=0;before[0].traverse(o=>{o.geometry?.addEventListener('dispose',()=>releases++);o.material?.addEventListener('dispose',()=>releases++);});
 const keep=new Set(next.userData.materials.values());first.userData.releasePlants(keep);disposeObject(first,{keepMaterials:keep});
 assert.equal(releases,0,'previous yard disposal preserves adopted resources');
 next.userData.releasePlants();disposeObject(next);assert.ok(releases>0,'final disposal releases the plant');
});
await test('changed_preset_regenerates_only_that_plant',async()=>{
 const plan=planted(),first=(await buildPlants(plan)).group,before=plantObjects(first);
 plan.site.planting[1].preset='maple';globalThis.__plantGenerations=0;
 const next=(await buildPlants(plan,first)).group;next.userData.adoptParts();
 assert.equal(globalThis.__plantGenerations,1);
 const after=plantObjects(next);assert.equal(after[0],before[0]);assert.notEqual(after[1],before[1]);assert.equal(after[2],before[2]);
});
await test('fresh_and_reused_match',async()=>{
 for(const viewing of [false,true]){
  const plan=planted(),first=(await buildPlants(plan,null,'high',viewing)).group;
  plan.site.planting[0].at=[2,3];plan.site.planting[0].elevation=1.25;
  plan.site.planting[1].at=[-2,5];plan.site.planting[1].elevation=-.4;
  plan.site.terraces[0].height=5;
  const next=(await buildPlants(plan,first,'high',viewing)).group;next.userData.adoptParts();
  const fresh=(await buildPlants(plan,null,'high',viewing)).group;
  assert.deepEqual(plantSnapshot(next),plantSnapshot(fresh),'position, scale, rotation, geometry and materials match');
 }
});
await test('plant_reuse_covers_tiers_and_viewing',async()=>{
 const savedContext=Element.prototype.getContext;
 Element.prototype.getContext=function(){return {drawImage(){}};};
 try{
  for(const tier of ['low','medium','high','max'])for(const viewing of [false,true]){
   const plan=planted(),first=(await buildPlants(plan,null,tier,viewing)).group,before=plantObjects(first);
   plan.site.planting[1].at=[-2,5];plan.site.planting[1].elevation=.75;globalThis.__plantGenerations=0;
   const next=(await buildPlants(plan,first,tier,viewing)).group;next.userData.adoptParts();
   assert.equal(globalThis.__plantGenerations,0,tier+' move never generates/bakes');assert.deepEqual(plantObjects(next),before);
   const fresh=(await buildPlants(plan,null,tier,viewing)).group;
   const transforms=g=>plantObjects(g).map(o=>[o.name,o.position.toArray(),o.rotation.toArray(),o.scale.toArray()]);
   assert.deepEqual(transforms(next),transforms(fresh),tier+' transforms match fresh');
  }
 }finally{if(savedContext)Element.prototype.getContext=savedContext;else delete Element.prototype.getContext;}
});
await test('plant_appearance_changes_regenerate_only_the_changed_plant',async()=>{
 const edits=[p=>p.seed++,p=>p.height++,p=>p.scale=.7,p=>p.scale_axes=[.5,2,1],p=>p.rotation=70,
  p=>p.pitch=10,p=>p.roll=15,p=>p.tint='#123456',p=>p.casts_shadow=false,p=>p.kind='shrub',
  p=>p.id='renamed',p=>p.object_kind='lamp',p=>p.visible_in=['editor'],p=>p.custom={future:'field'}];
 for(const edit of edits){
  const plan=planted(),first=(await buildPlants(plan)).group,before=plantObjects(first);
  edit(plan.site.planting[0]);plan.site.planting[0].at=[2,3];globalThis.__plantGenerations=0;
  const next=(await buildPlants(plan,first)).group;next.userData.adoptParts();
  assert.equal(globalThis.__plantGenerations,1,String(edit));
  const after=plantObjects(next);assert.notEqual(after[0],before[0]);assert.equal(after[1],before[1]);assert.equal(after[2],before[2]);
  assert.deepEqual(plantSnapshot(next),plantSnapshot((await buildPlants(plan)).group));
 }
 for(const [tier,viewing] of [['medium',false],['high',true]]){
  const plan=planted(),first=(await buildPlants(plan)).group;globalThis.__plantGenerations=0;
  const next=(await buildPlants(plan,first,tier,viewing)).group;next.userData.adoptParts();
  assert.equal(globalThis.__plantGenerations,3,'tier/viewing form part of the appearance');
 }
});
await test('low_cards_follow_the_first_seed_for_a_shared_preset',async()=>{
 const savedContext=Element.prototype.getContext;
 Element.prototype.getContext=function(){return {drawImage(){}};};
 try{
  const plan=planted();plan.site.planting=plan.site.planting.slice(0,2);plan.site.planting[1].preset='oak';
  const first=(await buildPlants(plan,null,'low')).group,before=plantObjects(first);
  plan.site.planting.reverse();globalThis.__plantGenerations=0;
  const next=(await buildPlants(plan,first,'low')).group;next.userData.adoptParts();
  assert.equal(globalThis.__plantGenerations,1,'a new first seed rebakes the shared preset once');
  const after=plantObjects(next);
  assert.ok(after.every(o=>!before.includes(o)),'the shared baked appearance changed for both cards');
  for(let i=0;i<2;i++)assert.notEqual(after[i].children[0].material.map,before[1-i].children[0].material.map,'no stale card material');
  plan.site.planting[0].at=[5,6];globalThis.__plantGenerations=0;
  const moved=(await buildPlants(plan,next,'low')).group;moved.userData.adoptParts();
  assert.equal(globalThis.__plantGenerations,0,'moving with the same first seed never rebakes');
  assert.deepEqual(plantObjects(moved),after);
 }finally{if(savedContext)Element.prototype.getContext=savedContext;else delete Element.prototype.getContext;}
});
await test('plant_materials_survive_an_omitted_or_reset_material_cache',async()=>{
 for(const materials of [null,new Map()]){
  const plan=planted(),first=(await buildPlants(plan)).group,before=plantObjects(first);
  plan.site.planting[0].at=[2,3];globalThis.__plantGenerations=0;
  const next=(await buildYard(plan,{materials:{}},'high',{previous:first,materials})).group;next.userData.adoptParts();
  assert.equal(globalThis.__plantGenerations,0);assert.deepEqual(plantObjects(next),before);
  let disposed=0;const keep=new Set(next.userData.materials.values());
  for(const object of before)object.traverse(o=>{for(const m of o.material?[].concat(o.material):[]){
   assert.ok(keep.has(m),'adopted material belongs to the new yard');m.addEventListener('dispose',()=>disposed++);
  }});
  first.userData.releasePlants(keep);disposeObject(first,{keepMaterials:keep});assert.equal(disposed,0);
 }
});
await test('plant_order_removal_visibility_and_cancellation_preserve_ownership',async()=>{
 const plan=planted(),first=(await buildPlants(plan,null,'high',true)).group,before=plantObjects(first);
 plan.site.planting.reverse();plan.site.planting[0].at=[-2,5];globalThis.__plantGenerations=0;
 const abandoned=(await buildPlants(plan,first,'high',true)).group;
 const keep=new Set(first.userData.materials.values());abandoned.userData.releasePlants(keep);disposeObject(abandoned,{keepMaterials:keep});
 assert.ok(before.every(o=>o.parent===first&&!o.userData.disposed),'discarding a candidate leaves plants alive');
 const next=(await buildPlants(plan,first,'high',true)).group;next.userData.adoptParts();
 assert.equal(globalThis.__plantGenerations,0,'id-based plants survive reorder');
 assert.deepEqual(plantObjects(next),[...before].reverse());
 assert.deepEqual(plantSnapshot(next),plantSnapshot((await buildPlants(plan,null,'high',true)).group));
 let removed=0;before[1].traverse(o=>o.geometry?.addEventListener('dispose',()=>removed++));
 plan.site.planting.splice(1,1);plan.site.planting[0].visible_in=['editor'];
 const last=(await buildPlants(plan,next,'high',true)).group;last.userData.adoptParts();
 assert.deepEqual(plantObjects(last),[before[0]],'removed and hidden plants stay in the previous yard');
 const retained=new Set(last.userData.materials.values());next.userData.releasePlants(retained);disposeObject(next,{keepMaterials:retained});
 assert.ok(removed>0,'removed geometry is released');assert.equal(before[0].userData.disposed,undefined);
});
await test('stair_edit_keeps_neighbour_and_only_changed_footprints_invalidate_grass',async()=>{
 const plan={buildings:[],materials:{},site:{terraces:[0,20].map((x,i)=>({id:'pad'+i,polygon:square(x,0,10),height:3,blend:0,
  edges:[{edge:'sharp',stair:{riser_in:7,tread_in:11,treads:true}},...Array.from({length:3},()=>({edge:'sharp'}))]}))}};
 const view=await mount(plan);
 try{
  const old=yard(view),neighbour=old.children.filter(o=>o.userData.padEdgeId==='pad1');assert.ok(neighbour.length);
  const changed=structuredClone(plan);changed.site.terraces[0].edges[0].stair.riser_in=6;
  const before=yardPartKeys(plan,{materials:{}},'high'),after=yardPartKeys(changed,{materials:{}},'high');
  assert.deepEqual(YARD_PARTS.filter(k=>before[k]!==after[k]),['retaining_walls'],'same six-tread footprint');
  const longer=structuredClone(changed);longer.site.terraces[0].edges[0].stair.riser_in=5;
  assert.notEqual(yardPartKeys(longer,{materials:{}},'high').grass,after.grass,'longer flight changes the grass mask');
  await view.rebuild(changed);assert.ok(neighbour.every(o=>yard(view).children.includes(o)),'neighbour keeps its exact meshes');
  assert.ok(old.children.every(o=>o.userData.padEdgeId!=='pad1'),'adopt before old yard release');
  const base=yardKey(changed,{materials:{}},'high');
  for(const edit of [s=>s.tread_in=12,s=>s.treads=false,s=>s.materials={riser:{id:'brick'}},s=>s.rail={style:'panel',height_in:42}]){
   const p=structuredClone(changed);edit(p.site.terraces[0].edges[0].stair);assert.notEqual(yardKey(p,{materials:{}},'high'),base);
  }
  const w=structuredClone(changed);w.site.terraces[0].edges[0]={edge:'sharp',wall:{material:'block',cap:{thickness_in:2,overhang_in:1},rail:{style:'pickets',height_in:36}}};
  const wk=yardPartKeys(w,{materials:{}},'high');
  for(const [i,edit] of [v=>v.cap.thickness_in=3,v=>v.cap.overhang_in=2,v=>v.materials={cap:{id:'brick'}},
    v=>v.rail.style='cable',v=>v.rail.height_in=42,v=>v.rail.materials={rail:{id:'metal'}}].entries()){
   const p=structuredClone(w);edit(p.site.terraces[0].edges[0].wall);const pk=yardPartKeys(p,{materials:{}},'high');
   assert.deepEqual(YARD_PARTS.filter(k=>wk[k]!==pk[k]),i===1?['retaining_walls','grass']:['retaining_walls'],'wall edit '+i);
  }
 }finally{view.dispose();}
});
await test('an_equivalent_rederived_outline_keeps_the_yard_key', async()=>{
 // The shape the server re-derived on the first edit in Chromium: extra collinear corners,
 // float noise and another start corner.
 const a=[[14.33,52],[30.67,52],[30.67,66],[14.33,66]];
 const b=[[30.667777777777776,59],[30.67,66],[14.329999999999998,66],[14.332222222222223,54],[14.333333333333334,52],[30.67,52]];
 assert.deepEqual(canonicalOutline(b),canonicalOutline(a));
 assert.deepEqual(canonicalOutline([...a].reverse()),canonicalOutline(a),'winding does not matter');
 assert.notDeepEqual(canonicalOutline([[14.33,52],[30.67,52],[30.67,67],[14.33,66]]),canonicalOutline(a),'a real change still differs');
 const plan=fixture(),other=structuredClone(plan);
 plan.buildings[0].rooms=[...(plan.buildings[0].rooms||[]),{id:'porch',kind:'porch',level:'L1',state:'settled',polygon:a}];
 other.buildings[0].rooms=[...(other.buildings[0].rooms||[]),{id:'porch',kind:'porch',level:'L1',state:'settled',polygon:b}];
 assert.equal(yardKey(other,{materials:{}},'high'),yardKey(plan,{materials:{}},'high'));
});
for(const editor of [true,false]) {
 await test(`yard_reused_when_only_building_material_changes (${editor?'editor':'live'})`,async()=>{
  const plan=fixture(),v=await mount(plan,editor),group=yard(v),mats=group.userData.materials;
  const geometries=[];group.traverse(o=>{if(o.geometry)geometries.push(o.geometry);});
  let releases=0;for(const resource of [...geometries,...new Set(mats.values())])resource.addEventListener('dispose',()=>releases++);
  try {
   plan.buildings[0].materials={siding:{id:'painted_trim',color:'#112233'}};
   plan.materials.siding={id:'board_and_batten',color:'#765432'};
   const record=beginEdit({op:'set_material'});await v.rebuild(plan,{timing:record});
   assert.equal(yard(v),group);assert.equal(group.userData.materials,mats);assert.equal(releases,0);
   assert.equal(record.detail.yard,0);assert.equal(record.yard_reused,true);
   // Comparing snapshots must also work when callers mutate view.plan in place.
   v.plan.buildings[0].materials.siding.color='#abcdef';
   const again=beginEdit({op:'set_material'});await v.rebuild(v.plan,{timing:again});
   assert.equal(yard(v),group);assert.equal(again.yard_reused,true);assert.equal(releases,0);
  }finally{v.dispose();}
  assert.ok(releases>0,'retained resources are released at final disposal');
 });
 await test(`yard_rebuilt_when_site_changes (${editor?'editor':'live'})`,async()=>{
  const v=await mount(fixture(),editor),group=yard(v);let disposed=0;
  group.traverse(o=>o.geometry?.addEventListener('dispose',()=>disposed++));
  try{
   v.plan.site.fence[0].polyline[1][0]+=1;
   const record=beginEdit({op:'move'});await v.rebuild(v.plan,{timing:record});
   assert.notEqual(yard(v),group);assert.equal(record.yard_reused,false);assert.ok(record.detail.yard>0);assert.ok(disposed>0);
   assert.equal(yard(v).userData.materials,group.userData.materials,'geometry edits retain compatible materials');
   for(const name of ['terrain','grass','plants','fences','hardscape','pool','fire_pits','retaining_walls','cards','batch','models','materials'])
    assert.ok(Number.isFinite(record.detail['yard_'+name]),name);
   assert.ok(Object.entries(record.detail).filter(([k])=>k.startsWith('yard_')).reduce((n,[,v])=>n+v,0)<=record.detail.yard+1);
  }finally{v.dispose();}
 });
}
await test('yard_rebuilt_when_terrain_or_footprint_changes',async()=>{
 const v=await mount(fixture());
 try{
  for(const change of [p=>p.site.terraces[0].height++,p=>p.buildings[0].levels[0].outline[0][0]++,p=>p.buildings[0].position[0]++]){
   const group=yard(v),plan=structuredClone(v.plan);change(plan);
   const record=beginEdit({op:'set'});await v.rebuild(plan,{timing:record});
   assert.notEqual(yard(v),group);assert.equal(record.yard_reused,false);assert.ok(record.detail.yard>0);
  }
 }finally{v.dispose();}
});
await test('yard_rebuilt_when_tier_changes',async()=>{
 // The production tier control remounts the view; there is no in-place tier setter.
 const p=fixture(),high=await mount(p,true,'high'),low=await mount(p,true,'low');
 try{
  assert.notEqual(yardKey(p,{},'high'),yardKey(p,{},'low'));
  assert.notEqual(yard(high),yard(low));
  // A retained yard from a different tier must fail the same rebuild comparison.
  const previous=yard(high);previous.userData.yardKey=yardKey(p,{},'low');
  previous.userData.yardMaterialKey='different tier';
  const record=beginEdit({op:'set'});await high.rebuild(p,{timing:record});
  assert.notEqual(yard(high),previous);assert.equal(record.yard_reused,false);
 }finally{high.dispose();low.dispose();}
});
await test('preserveYard remains explicit and does not certify a changed plan',async()=>{
 const v=await mount(fixture()),group=yard(v);
 try{
  const p=structuredClone(v.plan);p.site.fence[0].height++;
  const a=beginEdit({op:'set'});await v.rebuild(p,{preserveYard:true,timing:a});
  assert.equal(yard(v),group);assert.equal(a.yard_reused,true);assert.equal(a.detail.yard,0);
  const b=beginEdit({op:'set'});await v.rebuild(p,{timing:b});
  assert.notEqual(yard(v),group);assert.equal(b.yard_reused,false);
 }finally{v.dispose();}
});
await test('yard materials invalidate on resolved kit or manifest changes',async()=>{
 const kit={materials:{fence:{asset:'wood',color:'#665544'}},manifest:{wood:{kind:'material',revision:1}}};
 const plan=fixture();delete plan.site.fence[0].materials;
 const v=await mount(plan,true,'high',kit);
 try{
  for(const change of [()=>kit.materials.fence.color='#abcdef',()=>kit.manifest.wood.revision++]){
   const previous=yard(v),materials=previous.userData.materials;let releases=0;
   for(const m of new Set(materials.values()))m.addEventListener('dispose',()=>releases++);
   change();const record=beginEdit({op:'set'});await v.rebuild(v.plan,{timing:record});
   assert.notEqual(yard(v),previous);assert.notEqual(yard(v).userData.materials,materials);assert.equal(record.yard_reused,false);assert.ok(releases>0);
  }
 }finally{v.dispose();}
});
await test('household_revision_reaches_both_yard_keys_and_material_cache',async()=>{
 const id='material-yard',unused='material-unused';
 for(const useSlot of [false,true])for(const useWindow of [false,true]){
  const entry={kind:'material',household:true,revision:7,maps:{},params:{tint:'#123456'}};
  const kit={materials:{fence:{asset:useSlot?'wood':id,color:'#665544'}},manifest:{[id]:entry,[unused]:{...entry}}};
  const plan={buildings:[],materials:{},site:{fence:[{id:'f',polyline:[[0,0],[2,0]],height:3,
   ...(useSlot?{materials:{boards:{id}}}:{})}]}};
  const saved=window.twinManifest;
  if(useWindow){window.twinManifest=kit.manifest;delete kit.manifest;}
  try{
   const before=yardKey(plan,kit,'high'),beforeMaterials=yardMaterialKey(plan,kit,'high'),cache=new Map();
   const first=await buildYard(plan,kit,'high',{materials:cache});
   const names=group=>{const found=new Set();group.traverse(o=>{for(const m of o.material?[].concat(o.material):[])if(m.name==='fence')found.add(m);});return found;};
   const firstMaterials=names(first.group);
   const known=useWindow?window.twinManifest:kit.manifest;known[unused].revision++;
   assert.equal(yardKey(plan,kit,'high'),before,'unused household revision preserves yard');
   assert.equal(yardMaterialKey(plan,kit,'high'),beforeMaterials);
   entry.revision++;
   assert.notEqual(yardKey(plan,kit,'high'),before,'used household revision rebuilds yard');
   assert.notEqual(yardMaterialKey(plan,kit,'high'),beforeMaterials,'used revision invalidates materials');
   const second=await buildYard(plan,kit,'high',{materials:cache});
   assert.ok([...names(second.group)].some(m=>!firstMaterials.has(m)),'retained cache creates a new instance for a new revision');
  }finally{window.twinManifest=saved;}
 }
});
await test('key_covers_every_buildYard_input',()=>{
 const p=fixture(),b=p.buildings[0];
 p.site.pool.features=[{id:'ledge',kind:'ledge',polygon:square(5,5,1),depth_in:10},
  {id:'steps',kind:'steps',polygon:square(5,5,1),treads:3,entry_edge:0},
  {id:'spa',kind:'spa',polygon:square(5,5,1),mode:'raised',raise_in:12,depth_in:36,spillover:true,
   materials:{coping:{id:'coping-slot'},interior:{id:'inside-slot'},wall:{id:'wall-slot'}}}];
 b.foundation={mode:'auto',offset_ft:1};b.base=1;
 b.porches=[{id:'porch',polygon:square(0,0),level:b.levels[0].id,floor:1}];
 b.rooms.push({id:'porch-room',kind:'porch',state:'settled',level:b.levels[0].id,polygon:square(0,0),floor_offset_ft:1});
 const object={id:'object',kind:'chair',asset:'model',at:[1,1],elevation:1,visible_in:['viewer','editor'],scale:1,scale_axes:[1,1,1],pitch:1,rotation:1,roll:1,tint:'#123456',casts_shadow:true,object_kind:'lamp',emissive:true,emissive_color:'#ffffff',light_entity:'light.test',preset:'oak',height:4,seed:1};
 p.site.furniture=[object];p.site.planting=[structuredClone(object)];
 p.site.terraces.push({polygon:square(4,4),height:1,blend:2,edges:[]});
 p.site.hardscape.push({polygon:square(0,0),elevation:0,material:'paving',materials:{surface:{id:'patio-slot'}}});
 p.site.fire_pit.push({id:'square-fire',shape:'square',polygon:square(0,0),fuel:'wood'});
 p.site.edges.push({points:[[0,0],[1,1]],polyline:[[0,0],[2,2]]});
 const kit={materials:{lawn:{asset:'grass',color:'#445566',revision:1},fence:{asset:'wood'},custom:{asset:'slot-alias',revision:1}},
  furniture:{chair:'model'},manifest:{grass:{kind:'material',revision:1},model:{kind:'model',model:'model.glb',files:{'model.glb':'hash'},revision:1}}};
 let checked=0;
 function mutations(root,path=[],skip=()=>false){
  const out=[];
  for(const [k,v] of Object.entries(root)){
   const next=[...path,k];if(skip(next))continue;
   if(v!==null&&typeof v==='object')out.push(...mutations(v,next,skip));else out.push(next);
  }return out;
 }
 const mutate=(root,path)=>{const parent=path.slice(0,-1).reduce((o,k)=>o[k],root),k=path.at(-1),v=parent[k];parent[k]=typeof v==='number'?v+1:typeof v==='boolean'?!v:String(v)+'-changed';};
 function check(change,label,source=p,sourceKit=kit){
  const next=structuredClone(source),nextKit=structuredClone(sourceKit);change(next,nextKit);
  assert.notEqual(yardKey(next,nextKit,'high'),yardKey(source,sourceKit,'high'),label);checked++;
 }
 // An edge with both points and polyline draws its blades from points; its polyline is never read.
 for(const path of mutations(p.site,[],q=>q.join('.')==='edges.1.polyline'))check(n=>mutate(n.site,path),'site.'+path.join('.'));
 for(const path of [['position','0'],['rotation'],['base'],['foundation','mode'],['foundation','offset_ft'],['levels','0','outline','0','0'],
   ['levels','0','id'],['porches','0','polygon','0','0'],['porches','0','level'],['porches','0','floor'],
   ['rooms',String(b.rooms.length-1),'kind'],['rooms',String(b.rooms.length-1),'state'],['rooms',String(b.rooms.length-1),'level'],
   ['rooms',String(b.rooms.length-1),'polygon','0','0'],['rooms',String(b.rooms.length-1),'floor_offset_ft']])
  check(n=>mutate(n.buildings[0],path),'building.'+path.join('.'));
 const fallback=structuredClone(p);fallback.buildings[0].levels.forEach(l=>delete l.outline);
 check(n=>n.buildings[0].walls.push({from:[-999,-999],to:[999,999]}),'wall fallback',fallback);
 const roomFallback=structuredClone(fallback);roomFallback.buildings[0].walls=[];
 check(n=>n.buildings[0].rooms.push({level:b.levels[0].id,polygon:square(-999,-999)}),'room fallback',roomFallback);
 const wallFallback=structuredClone(fallback);wallFallback.buildings[0].rooms=[];
 wallFallback.buildings[0].walls=[{from:[0,0],to:[4,4]}];
 for(const end of ['from','to'])for(const axis of [0,1])
  check(n=>n.buildings[0].walls[0][end][axis]+=(end==='from'?-1:1),'wall fallback '+end+axis,wallFallback);
 const alias=structuredClone(p);delete alias.buildings[0].porches;alias.buildings[0].porch={polygon:square(0,0),floor:1};
 check(n=>n.buildings[0].porch.floor++,'legacy porch',alias);
 check(n=>n.buildings[0].levels[1].elevation=-99,'lowest level changes footprint');
 for(const path of mutations(kit.materials.lawn))check((n,k)=>mutate(k.materials.lawn,path),'kit lawn.'+path.join('.'));
 // Since v2.499.1009 the key projects only inputs loadModel reads; a built-in's kind is not one of them.
 for(const path of mutations(kit.manifest,[],p=>p.length===2&&p[0]==='model'&&p[1]==='kind'))check((n,k)=>mutate(k.manifest,path),'manifest.'+path.join('.'));
 check(n=>{delete n.site.furniture[0].asset;},'furniture kind resolves kit');
 const kind=structuredClone(p);delete kind.site.furniture[0].asset;
 check((n,k)=>k.furniture.chair='other','kit furniture',kind);
 check(n=>n.materials.lawn={id:'grass',color:'#abcdef'},'plan role override');
 const sidingSlot=structuredClone(p);sidingSlot.materials.siding={id:'grass',color:'#112233'};
 sidingSlot.site.beds[0].materials.fill={id:'siding'};
 check(n=>n.materials.siding.color='#abcdef','building role explicitly used by yard slot',sidingSlot);
 check(n=>n.site.terraces.reverse(),'pad order');
 const aliases=structuredClone(p);aliases.buildings[0].porch={id:'porch',polygon:square(9,9),floor:2};
 check(n=>n.buildings[0].porches[0].id='different','porch id affects alias deduplication',aliases);
 const slotted=structuredClone(p);slotted.site.beds[0].materials.fill={id:'slot-alias'};
 check((n,k)=>k.materials.custom.revision++,'slot alias ref/revision',slotted);
 check((n,k)=>k.materials.custom.asset='other','slot alias selection',slotted);
 const asset={id:'import-test',model:'m.glb',revision:1,kind:'chair',size:[1,2,3],triangles:400000,lods:[{name:'lod2.glb'}],files:{'m.glb':'hash'}};
 const imported=structuredClone(p);imported.site.furniture[0].asset=asset.id;
 for(const path of mutations(asset,[],p=>p.join('.')==='id')){
  // The revision mutation must not make rememberImport reject later baseline resets as stale.
  forgetImport(asset.id);
  rememberImport(asset);const before=yardKey(imported,kit,'high');
  const next=structuredClone(asset);mutate(next,path);rememberImport(next);
  assert.notEqual(yardKey(imported,kit,'high'),before,'import.'+path.join('.'));checked++;
 }
 const fallbackKit=structuredClone(kit);delete fallbackKit.manifest;
 const savedManifest=window.twinManifest;
 try{
  window.twinManifest=structuredClone(kit.manifest);const before=yardKey(p,fallbackKit,'high');
  window.twinManifest.grass.revision++;
  assert.notEqual(yardKey(p,fallbackKit,'high'),before,'window manifest fallback');checked++;
 }finally{window.twinManifest=savedManifest;}
 assert.notEqual(yardKey(p,kit,'high'),yardKey(p,kit,'high',{viewing:true}));checked++;
 assert.notEqual(yardKey(p,kit,'high'),yardKey(p,kit,'low'));checked++;
 console.log(`    ${checked} input mutations checked`);
});

// Per-part reuse (edit speed step 3): an edit rebuilds only the yard parts whose inputs changed.
// A part's identity is the list of objects tagged with it (the yard root stays flat).
const parts=v=>{const out={};for(const o of yard(v)?.children||[])(out[o.userData.yardPart]||=[]).push(o);return out;};
const same=(a=[],b=[])=>a.length===b.length&&a.every((o,i)=>o===b[i]);
async function partEdit(change,expectRebuilt,label){
 const plan=fixture();plan.site.planting=[{id:'oak',kind:'tree',preset:'oak',at:[2,2],height:12,seed:1}];
 const v=await mount(plan,true);
 try{
  const before=parts(v);
  change(plan);
  const record=beginEdit({op:'edit'});await v.rebuild(plan,{timing:record});
  const after=parts(v);
  const rebuilt=YARD_PARTS.filter(n=>(before[n]||after[n])&&!same(after[n],before[n])).sort();
  // A refreshed plants part retains its matching objects. Other rebuilt parts
  // replace their drawn objects; timing still lists every refreshed part.
  const drawn=expectRebuilt.filter(n=>n!=='plants'&&(before[n]?.length||after[n]?.length));
  if(expectRebuilt.includes('plants'))assert.ok(same(after.plants,before.plants),label+': unchanged plant appearances keep their objects');
  assert.deepEqual(rebuilt,[...drawn].sort(),label+': rebuilt '+JSON.stringify(rebuilt));
  assert.deepEqual([...record.yard_rebuilt_parts].sort(),[...expectRebuilt].sort(),label+' timing');
  for(const n of YARD_PARTS)if(!expectRebuilt.includes(n))for(const o of after[n]||[])assert.ok(o.parent===yard(v),label+': '+n+' adopted into the new yard');
  const order=yard(v).children.map(o=>YARD_PARTS.indexOf(o.userData.yardPart));
  assert.ok(order.every((x,i)=>i===0||x>=order[i-1]),label+': stable part order');
 }finally{v.dispose();}
}
await test('fence_edit_rebuilds_only_fences',()=>partEdit(p=>{p.site.fence[0].polyline[1][0]+=1;},['fences'],'fence'));
await test('plant_move_rebuilds_only_plants',()=>partEdit(p=>{p.site.planting[0].at[0]+=1;},['plants'],'plant'));
await test('fence_material_slot_rebuilds_only_fences',()=>partEdit(p=>{p.site.fence[0].materials.boards={id:'other-slot'};},['fences'],'fence slot'));
await test('pad_edit_rebuilds_terrain_and_what_sits_on_it',()=>partEdit(p=>{p.site.terraces[0].height+=1;},
 ['terrain','plants','fences','hardscape','pool','fire_pits','retaining_walls','furniture','grass'],'pad'));
await test('pool_outline_rebuilds_pool_terrain_hardscape_holes_and_grass_mask',()=>partEdit(p=>{p.site.pool.polygon[0][0]-=.5;},['terrain','hardscape','pool','grass'],'pool outline'));
await test('pool_depth_rebuilds_only_pool',()=>partEdit(p=>{p.site.pool.depth+=1;},['pool'],'pool depth'));
await test('replaced_slot_material_is_released',async()=>{
 const plan=fixture();const v=await mount(plan,true);
 try{
  const map=()=>yard(v).userData.materials;
  const old=[...map().values()];
  plan.site.fence[0].materials.boards={id:'other-slot'};
  await v.rebuild(plan,{timing:beginEdit({op:'edit'})});
  const used=new Set();yard(v).traverse(o=>{for(const m of o.material?[].concat(o.material):[])used.add(m);});
  for(const m of map().values())assert.ok(used.has(m),'the new yard keeps only materials a mesh uses');
  assert.ok(old.some(m=>!used.has(m)),'the replaced boards material is no longer kept');
 }finally{v.dispose();}
});
await test('part_key_guard',()=>{
 const p=fixture();
 p.site.planting=[{id:'oak',kind:'tree',preset:'oak',at:[2,2],height:12,seed:1}];
 p.site.furniture=[{id:'chair',kind:'chair',asset:'model',at:[1,1]}];
 p.site.pool.features=[{id:'spa',kind:'spa',polygon:square(5,5,1),mode:'raised',raise_in:12,depth_in:36,spillover:true}];
 const kit={materials:{lawn:{asset:'grass'},fence:{asset:'wood'}},furniture:{chair:'model'},manifest:{}};
 const ALL=YARD_PARTS.filter(n=>n!=='grass'||true);
 const grade=['terrain','plants','fences','hardscape','pool','fire_pits','retaining_walls','furniture','grass'];
 // What each site input feeds, by the part builders' reads.
 const expected=path=>{
  const [list,,field,...rest]=path;
  if(list==='lot')return ['terrain','grass'];
  if(list==='terraces'){
   if(field==='edges'&&rest[1]==='wall'||field==='edges'&&rest.includes('wall')){
    const footprint=rest.at(-1)==='thickness_in'&&!rest.includes('cap') || rest.at(-1)==='overhang_in';
    return footprint?['retaining_walls','grass']:['retaining_walls'];
   }
   if(field==='edges'&&rest[1]==='edge')return grade;
   return grade;
  }
  if(list==='hardscape')return ['kind','polygon','points','width','corner','smooth','radius','edging'].includes(field)?['hardscape','grass']:['hardscape'];
  if(list==='beds')return field==='polygon'?['hardscape','grass']:['hardscape'];
  if(list==='pool'){
   // pool is an object, not a list: path is pool.<field>[.<index>.<sub>…]
   const poolField=path[1],sub=path[3];
   // The pool outline and spa outlines (and whether a feature is a spa) cut the
   // lawn and patio holes.
   if(poolField==='polygon'||poolField==='features'&&(sub==='polygon'||sub==='kind'))return ['terrain','hardscape','pool','grass'];
   if(poolField==='coping')return ['pool','grass'];
   return ['pool'];
  }
  if(list==='fire_pit')return ['shape','polygon','at','radius','rotation'].includes(field)?['fire_pits','grass']:['fire_pits'];
  if(list==='edges')return field==='polygon'?['hardscape','grass']:['points','polyline'].includes(field)?['grass']:['hardscape'];
  if(list==='fence')return ['fences'];
  if(list==='planting')return ['plants'];
  if(list==='furniture')return ['furniture'];
  return null;
 };
 const mutations=(root,path=[])=>Object.entries(root).flatMap(([k,v])=>v!==null&&typeof v==='object'?mutations(v,[...path,k]):[[...path,k]]);
 const mutate=(root,path)=>{const parent=path.slice(0,-1).reduce((o,k)=>o[k],root),k=path.at(-1),v=parent[k];parent[k]=typeof v==='number'?v+1:typeof v==='boolean'?!v:String(v)+'-changed';};
 const base=yardPartKeys(p,kit,'high');let checked=0;const wrong=[];
 for(const path of mutations(p.site)){
  const want=expected(path);if(!want)continue;
  const next=structuredClone(p);mutate(next.site,path);
  const keys=yardPartKeys(next,kit,'high');
  const changed=YARD_PARTS.filter(n=>keys[n]!==base[n]);
  // A part may legitimately ignore a field (a material name that resolves to the same role);
  // it must never change when the field is not its input.
  const extra=changed.filter(n=>!want.includes(n));
  if(extra.length||!changed.length)wrong.push(path.join('.')+' changed '+JSON.stringify(changed)+' want '+JSON.stringify(want));
  checked++;
 }
 assert.deepEqual(wrong,[],wrong.join('\n'));
 console.log(`    ${checked} per-part mutations checked`);
});
await test('irrelevant authoring metadata and building finishes leave key unchanged',()=>{
 const p=fixture(),key=yardKey(p,{},'high');
 p.site.fence[0].src={step:'person'};p.site.yard_rooms=[{polygon:square(0,0)}];
 p.buildings[0].name='renamed';p.buildings[0].materials={siding:{color:'#123456'}};p.materials.siding={id:'new',color:'#ffffff'};
 assert.equal(yardKey(p,{},'high'),key);
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
