"""Building cache acceptance through real generator, mounted view and editor cards.

CPU Node proof. The renderer and external tree generator use the editor rig;
all house, material, pick, selection and card modules execute normally.
"""
import json
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const T=await import('three');
const {buildTwin,buildingKey}=await import(file('static/twin/twin_generator.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {disposeObject,rememberImport}=await import(file('static/twin/twin_library.js'));
const {beginEdit}=await import(file('static/twin/edit_timing.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const square=(x,y,w=12)=>[[x,y],[x+w,y],[x+w,y+w],[x,y+w]];
const makeBuilding=(id,x)=>({id,name:id,position:[x,0],rotation:0,base:0,
 foundation:{mode:'auto',offset_ft:.5,thickness_ft:1},materials:{},
 levels:[{id:'L1',name:'Ground',elevation:0,ceiling:8,outline:square(0,0)}],
 walls:square(0,0).map((from,i,a)=>({id:'w'+i,level:'L1',from,to:a[(i+1)%4],height:8,thickness:.5,exterior:true,state:'settled'})),
 rooms:[{id:'room',level:'L1',name:'Kitchen',polygon:square(0,0),state:'settled'}],
 openings:[{id:'door',wall:'w0',level:'L1',kind:'door',at:3,width:3,sill:0,head:7,state:'settled'}],
 roof:{sections:[{id:'roof',kind:'gable',rect:[0,0,12,12],plate:8,pitch:6,ridge:'x',overhang:1}],flags:[]},
 roofs:[],stairs:[],anchors:[],items:[],fixtures:[],lights:[]});
const fixture=()=>({buildings:[makeBuilding('a',0),makeBuilding('b',40)],materials:{},site:{terraces:[]}});
const kit={materials:Object.fromEntries(['floor','patio_concrete','siding','interior_wall','roof','trim','window_frame','door','porch_ceiling','base','lattice','counter','stainless'].map(role=>[role,{asset:role,color:'#bbccee'}])),manifest:{}};
async function build(plan=fixture(),opts={}){const twin=buildTwin(plan,kit,'low',opts);await twin.ready;return twin;}
const domains=(twin,id)=>[...Object.values(twin.groups.levels).filter(g=>g.userData.buildingId===id),
 ...['roof','gableFull','gableCut','lights'].flatMap(n=>twin.groups[n].children.filter(g=>g.userData.buildingId===id))];
async function edited(mutate){const plan=fixture(),old=await build(plan),p=structuredClone(plan);mutate(p);
 const oldDomains=Object.fromEntries(plan.buildings.map(b=>[b.id,domains(old,b.id)]));
 const timing=beginEdit({op:'set'}),next=await build(p,{previous:old,timing});
 // Async preparation must not steal any retained objects from the live scene.
 for(const id of next.buildingsReused)for(const g of domains(old,id))assert.ok(g.parent,'old domain still attached');
 next.adoptBuildings();return {old,next,p,timing,oldDomains};}
await test('edit_one_building_rebuilds_only_it',async()=>{
 const {old,next,timing,oldDomains}=await edited(p=>p.buildings[0].openings[0].width=4);
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
 assert.deepEqual(domains(next,'b'),oldDomains.b);
 assert.equal(next.buildings.get('b').model,old.buildings.get('b').model);
 assert.equal(next.groups.levels['b:L1'],old.groups.levels['b:L1']);
 assert.notEqual(next.groups.levels['a:L1'],old.groups.levels['a:L1']);
 for(const name of ['pieces','pieceBounds','pickObjects','roofSurfaces'])for(const [key,value] of old[name])if(key.startsWith('b:'))assert.equal(next[name].get(key),value,name+':'+key);
 assert.ok(old.roofSurfaces.get('b').positions.length>0);assert.equal(next.roofSurfaces.get('b'),old.roofSurfaces.get('b'));
 assert.deepEqual(timing.buildings_reused,['b']);assert.deepEqual(timing.buildings_rebuilt,['a']);
 assert.equal(timing.buildings.find(b=>b.id==='b').generate,0);assert.ok(timing.buildings.find(b=>b.id==='a').generate>0);
 assert.equal(timing.counts.buildings,2);assert.equal(timing.counts.levels,2);
});
await test('material_override_on_one_building_rebuilds_only_it',async()=>{
 const {next}=await edited(p=>p.buildings[0].materials.siding={id:'siding',color:'#334455'});
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
});
await test('plan_level_material_change_rebuilds_all_that_use_it',async()=>{
 const {next}=await edited(p=>p.materials.siding={id:'siding',color:'#334455'});assert.deepEqual(next.buildingsRebuilt,['a','b']);
 const plan=fixture();plan.buildings[1].materials.siding={id:'siding',color:'#ffffff'};
 const old=await build(plan),p=structuredClone(plan);p.materials.siding={id:'siding',color:'#334455'};
 const selective=await build(p,{previous:old});assert.deepEqual(selective.buildingsRebuilt,['a']);assert.deepEqual(selective.buildingsReused,['b']);
});
await test('terrain_change_under_a_building_rebuilds_it',async()=>{
 const {old,next}=await edited(p=>p.site.terraces.push({polygon:square(-2,-2,16),height:2,blend:0}));
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
 assert.notEqual(next.levelElevations['a:L1'],old.levelElevations['a:L1']);assert.equal(next.levelElevations['b:L1'],old.levelElevations['b:L1']);
});
await test('yard_only_edit_reuses_every_building',async()=>{
 const {next}=await edited(p=>p.site.fence=[{polyline:[[0,-8],[20,-8]],height:5}]);assert.deepEqual(next.buildingsRebuilt,[]);assert.deepEqual(next.buildingsReused,['a','b']);
});
await test('household_draw_calls_do_not_increase_after_building_reuse',async()=>{
 const calls=root=>{let n=0;root.traverseVisible(o=>{if(o.isMesh&&!o.layers.isEnabled(31))n+=Array.isArray(o.material)?o.geometry.groups.filter(g=>o.material[g.materialIndex]?.visible).length:Number(o.material.visible);});return n;};
 for(const viewing of [false,true]){
  const old=buildTwin(input.household,input.householdKit,'high',{viewing});await old.ready;const before=calls(old.root);
  const p=structuredClone(input.household);p.buildings[0].openings[0].width+=.1;
  const next=buildTwin(p,input.householdKit,'high',{viewing,previous:old});await next.ready;next.adoptBuildings();
  assert.deepEqual(next.buildingsReused,['pool-house']);assert.equal(calls(next.root),before);assert.equal(before,viewing?71:42,'v2.499.861 baseline structure submissions');
  console.log(`  household ${viewing?'viewer':'editor'} structure: ${before} -> ${calls(next.root)} calls`);
 }
});
await test('building_key_guard',async()=>{
 const p=fixture(),b=p.buildings[0],k=structuredClone(kit),opts={viewing:false,showAnchors:false,editableLevel:null};
 b.joints=[{id:'j',at:[0,0]}];b.stairs=[{id:'stair',from:[0,0],to:[4,0],width:2,rise_to:8,risers:12,style:'open'}];
 b.porch={id:'porch',polygon:square(0,-4,4),floor:0,foundation:{type:'posts',materials:{posts:{id:'custom-post'}}}};
 b.porches=[{id:'porch2',polygon:square(8,-4,4),floor:0}];
 b.roofs=[{id:'roof-record',level:'L1',plate:8,area:square(0,0)}];
 b.solar_zones=[{id:'zone',roof:'roof',rect:[1,1,3,3],plane:[0,.5,8],count:1}];
 b.anchors=[{id:'parking',kind:'parking',host:{ground:true,at:[-2,0]},width:9,depth:18}];
 b.items=[{id:'chair',asset:'chair',host:{floor:'room',u:.5,v:.5},scale:1}];
 b.openings[0].model='door-model';b.fixtures=[{id:'counter',kind:'counter',level:'L1',rect:[0,0,2,2],height:3}];
 b.lights=[{id:'lamp',at:[2,2],level:'L1',kind:'recessed'}];
 b.levels[0].materials={floor:{id:'level-finish'}};b.walls[0].faces={left:{id:'face-finish'}};
 b.rooms[0].wall_material={id:'room-wall'};b.rooms[0].floor_material={id:'room-floor'};
 for(const role of Object.keys(k.materials))p.materials[role]={id:role,color:'#aabbcc'};
 k.materials['custom-post']={asset:'post-asset',color:'#bbccdd'};
 for(const id of ['chair','door-model','level-finish','face-finish','room-wall','room-floor','post-asset',...Object.keys(k.materials)])k.manifest[id]={kind:'material',revision:1,household:true};
 p.site.terraces=[{polygon:square(-4,-4,24),height:2,blend:4,edges:[{edge:'slope'}]}];
 const key=(p1=p,k1=k,o=opts,t='low')=>buildingKey(p1,p1.buildings[0],k1,t,o),before=key();let n=0;
 // Every leaf of the documented record, refs and grade (not just one sentinel per collection).
 const leaves=(value,path=[])=>value&&typeof value==='object'?Object.entries(value).flatMap(([name,v])=>leaves(v,[...path,name])):[path];
 const mutate=(value,path)=>{let target=value;for(const name of path.slice(0,-1))target=target[name];const last=path.at(-1),v=target[last];target[last]=typeof v==='number'?v+.25:typeof v==='boolean'?!v:String(v)+'-changed';};
 for(const path of leaves(b)){const clone=structuredClone(p);mutate(clone.buildings[0],path);assert.notEqual(key(clone),before,'building.'+path.join('.'));n++;}
 for(const path of leaves(p.site.terraces)){const clone=structuredClone(p);mutate(clone.site.terraces,path);assert.notEqual(key(clone),before,'grade.'+path.join('.'));n++;}
 // Every structural role used by this rich building (stainless requires a fixture).
 b.fixtures.push({id:'fridge',kind:'fridge',level:'L1',rect:[0,0,1,1],height:6});
 const richBefore=key();
 for(const role of Object.keys(kit.materials)){
  const clone=structuredClone(p);clone.materials[role].color='#112233';assert.notEqual(key(clone),richBefore,'plan role '+role);n++;
  const kk=structuredClone(k);kk.materials[role].roughness=.2;assert.notEqual(key(p,kk),richBefore,'kit role '+role);n++;
  const km=structuredClone(k);km.manifest[role].revision++;assert.notEqual(key(p,km),richBefore,'household revision '+role);n++;
 }
 for(const id of ['chair','door-model','level-finish','face-finish','room-wall','room-floor','post-asset']){
  const kk=structuredClone(k);kk.manifest[id].revision++;assert.notEqual(key(p,kk),richBefore,'resolved manifest '+id);n++;
 }
 for(const [name,value] of [['viewing',true],['showAnchors',true],['editableLevel','a:L1'],['editableLevel','b:L1']]){assert.notEqual(key(p,k,{...opts,[name]:value}),richBefore,name);n++;}
 assert.notEqual(key(p,k,opts,'high'),richBefore);n++;
 window.twinManifest=k.manifest;const fallback={materials:k.materials};const fb=key(p,fallback);window.twinManifest={...k.manifest,siding:{...k.manifest.siding,revision:8}};assert.notEqual(key(p,fallback),fb);delete window.twinManifest;n++;
 const unused=structuredClone(k);unused.materials.lawn={asset:'unused'};unused.manifest.unrelated={revision:9};assert.equal(key(p,unused),richBefore);
 const yard=structuredClone(p);yard.site.fence=[{height:9}];assert.equal(key(yard),richBefore);
 console.log(`  key guard: ${n} independent input mutations`);
});
await test('reused_resources_survive_and_changed_materials_are_released',async()=>{
 const plan=fixture(),old=await build(plan),entry=old.buildings.get('b'),geometry=old.pieces.get('b:w0')[0].geometry,material=entry.model.materials.get('siding');
 let disposed=0,replaced=0;geometry.addEventListener('dispose',()=>disposed++);material.addEventListener('dispose',()=>disposed++);
 old.buildings.get('a').model.materials.get('siding').addEventListener('dispose',()=>replaced++);
 const p=structuredClone(plan);p.buildings[0].openings[0].width=4;const next=await build(p,{previous:old});next.adoptBuildings();
 const keepMaterials=new Set(next.materials.values());disposeObject(old.root,{keepMaterials});old.materials.forEach(m=>{if(!keepMaterials.has(m))m.dispose();});
 assert.equal(disposed,0);assert.equal(next.pieces.get('b:w0')[0].geometry,geometry);
 assert.ok(replaced>0,'changed-only material is released');
 disposeObject(next.root);assert.ok(disposed>0);
});
await test('building_key_guard_sparse_buildings_and_effective_slot_aliases',async()=>{
 const p=fixture(),b=p.buildings[0];b.walls=[];b.openings=[];b.roof={sections:[]};
 b.levels.push({id:'L2',elevation:8,ceiling:8,outline:square(0,0)});b.rooms.push({id:'upper',level:'L2',polygon:square(0,0)});
 const changedKit=structuredClone(kit);changedKit.materials.interior_wall.color='#112233';
 assert.notEqual(buildingKey(p,b,kit,'low'),buildingKey(p,b,changedKit,'low'),'wall-free upper slabs read interior_wall');
 b.fixtures=[{id:'counter',kind:'counter',level:'L1',rect:[1,1,3,3],height:3}];
 assert.notEqual(buildingKey(p,b,kit,'low'),buildingKey(p,b,kit,'low',{editableLevel:'b:L1'}),'a focused level switches fixture visibility even in another building');
 b.porch={id:'porch',polygon:square(0,-4,4),floor:3,foundation:{type:'solid',materials:{solid:{id:'effective-asset'}}}};
 const k=structuredClone(kit);k.materials.custom={asset:'original-asset',color:'#aaaabb'};k.manifest['effective-asset']={kind:'material'};
 p.materials.custom={id:'effective-asset',color:'#112233'};
 const old=buildTwin(p,k,'low');await old.ready;const nextPlan=structuredClone(p);nextPlan.materials.custom.color='#abcdef';
 assert.notEqual(buildingKey(p,b,k,'low'),buildingKey(nextPlan,nextPlan.buildings[0],k,'low'),'slot alias resolves after plan overrides');
 const next=buildTwin(nextPlan,k,'low',{previous:old});await next.ready;assert.deepEqual(next.buildingsRebuilt,['a']);
 assert.ok([...next.buildings.get('a').model.materials.values()].some(m=>m.name==='custom'&&m.color.getHexString()==='abcdef'));
 const imported='import-'+'c'.repeat(32);b.items=[{id:'model',asset:imported,host:{floor:'room',u:.5,v:.5}}];
 rememberImport({id:imported,model:'first.glb',files:{'first.glb':true},lods:[]});const key=buildingKey(p,b,k,'low');
 rememberImport({id:imported,model:'second.glb',files:{'second.glb':true},lods:[{model:'far.glb',triangles:100}]});assert.notEqual(buildingKey(p,b,k,'low'),key);
 console.log('  key guard: 4 sparse/alias/import input mutations');
});
await test('discarded_candidate_does_not_steal_or_dispose_reused_building',async()=>{
 const plan=fixture(),old=await build(plan),domainsBefore=domains(old,'b'),geometry=old.pieces.get('b:w0')[0].geometry;let disposed=0;
 geometry.addEventListener('dispose',()=>disposed++);
 const p=structuredClone(plan);p.buildings[0].openings[0].width=4;const candidate=await build(p,{previous:old});
 disposeObject(candidate.root,{keepMaterials:new Set(old.materials.values())});
 assert.deepEqual(domains(old,'b'),domainsBefore);assert.equal(disposed,0);
 assert.ok(old.pickObjects.get('b:door').parent);assert.equal(old.pieces.get('b:w0')[0].geometry,geometry);
});
await test('shared_material_is_not_disposed_while_a_reused_building_owns_it',async()=>{
 const plan=fixture(),shared=new T.MeshStandardMaterial({name:'siding'});let disposed=0;shared.addEventListener('dispose',()=>disposed++);
 const old=await build(plan,{reuseMaterials:new Map([['siding',shared]])});assert.equal(old.buildings.get('a').model.materials.get('siding'),shared);assert.equal(old.buildings.get('b').model.materials.get('siding'),shared);
 const p=structuredClone(plan);p.buildings[0].openings[0].width=4;const next=await build(p,{previous:old});next.adoptBuildings();next.adoptBuildings();
 const keepMaterials=new Set(next.materials.values());disposeObject(old.root,{keepMaterials});old.materials.forEach(m=>{if(!keepMaterials.has(m))m.dispose();});
 assert.equal(disposed,0);assert.equal(next.buildings.get('b').model.materials.get('siding'),shared);disposeObject(next.root);assert.ok(disposed>0);
});
await test('mounted_editor_selection_hover_cards_and_picks_survive_other_building_edit',async()=>{
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await mountTwin(host,{plan:fixture(),kit,tier:'low',bake:false,preserveCamera:true});
 try{
  const group=view.groups.levels['b:L1'],box=view.worldBox('door','b'),oldGeometry=[];group.traverse(o=>{if(o.geometry)oldGeometry.push([o,o.geometry]);});
  let selection={pieceId:'door',buildingId:'b',kind:'opening'};
  const cards=createCards({getPlan:()=>view.plan,getKit:()=>kit,getLabel:()=> 'Annex door',getSelection:()=>({building:'b',level:'L1'}),canEdit:()=>true,edit:async()=>{},op:async()=>{},select(){},ask(){}});
  const paint=()=>{view.setSelection({selected:{id:'door',building:'b',kind:'opening'},hover:{id:'w0',building:'b',kind:'wall'},room:null});cards.draw(selection);};
  paint();assert.match(document.getElementById('piece-card').textContent,/Door/);
  const p=structuredClone(view.plan);p.buildings[0].openings[0].width=4;const timing=beginEdit({op:'resize_opening'});await view.rebuild(p,{timing});
  assert.deepEqual(timing.buildings_reused,['b']);assert.equal(view.groups.levels['b:L1'],group);assert.deepEqual(view.worldBox('door','b'),box);
  for(const [object,geometry] of oldGeometry)assert.equal(object.geometry,geometry);
  paint();let selected=0,hover=0;group.traverse(o=>{if(o.userData.selectionKey==='b:door'&&!o.userData.isHover)selected++;if(o.userData.selectionKey==='b:w0'&&o.userData.isHover)hover++;});
  assert.ok(selected>0);assert.ok(hover>0);assert.match(document.getElementById('piece-card').textContent,/Door/);
  assert.ok(document.getElementById('piece-card').querySelectorAll('input').some(n=>n.value===`3'-0"`),'card still reads the retained door width');
  // Raycast the retained room proxy with the actual plan camera.
  view.setView('b:L1');view.setPlanCamera('b:L1');const screen=view.screenOfFloor(8,8,'b:L1');
  const picked=view.pick(...screen);assert.equal(picked.building,'b');assert.equal(picked.id,'room');
  view.showLevels(['b:L1'],{faint:['b:L1']});assert.equal(view.groups.levels['a:L1'].visible,false);
  const p2=structuredClone(view.plan);p2.buildings[0].openings[0].width=5;await view.rebuild(p2);assert.equal(view.groups.levels['b:L1'],group);assert.equal(view.groups.levels['a:L1'].visible,false);
 }finally{view.dispose();}
});
await test('supplementary_ghosts_and_rebuildLevel_keep_correct_registries',async()=>{
 const plan=fixture();plan.buildings[1].openings.push({id:'loose',level:'L1',kind:'window',position:[6,6],width:2,sill:2,head:5,state:'ghost'});
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await mountTwin(host,{plan,kit,tier:'low',bake:false});try{
  await view.setEditableLevel('b:L1');const group=view.groups.levels['b:L1'],loose=view.worldBox('loose','b');assert.ok(loose);
  let disposed=0;group.traverse(o=>{if(o.userData.pieceId==='loose')o.material?.addEventListener('dispose',()=>disposed++);});
  const p=structuredClone(view.plan);p.buildings[0].openings[0].width=4;await view.rebuild(p);assert.equal(view.groups.levels['b:L1'],group);assert.deepEqual(view.worldBox('loose','b'),loose);assert.equal(disposed,0,'retained supplemental ghost/proxy materials stay alive');
  const before=view.worldBox('door','b'),flat=structuredClone(view.plan);flat.buildings[1].openings[0].width=5;
  view.rebuildLevel('b','L1',flat,{openings:['door']});assert.notDeepEqual(view.worldBox('door','b'),before);
  const timing=beginEdit({op:'set'});await view.rebuild(flat,{timing});assert.deepEqual(timing.buildings_rebuilt,['b']);assert.deepEqual(timing.buildings_reused,['a']);
 }finally{view.dispose();}
});
finish();
"""


if __name__ == '__main__':
    household = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    household_kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    household_kit['manifest'] = {}
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'household': household, 'householdKit': household_kit}, timeout=120)
    print(out)
    sys.exit(code or 0)
