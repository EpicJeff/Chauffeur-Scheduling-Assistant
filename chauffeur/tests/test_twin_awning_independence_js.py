"""Task 3: real generator buffers stay independent of supported roof groups.

The loader observes the real meshes immediately before static batching; it does
not replace any builder or infer behavior by searching production source.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from twin_editor_dom import PRELUDE, run_node
from test_twin_awning_golden_js import baseline_sources

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {createHash}=await import('node:crypto');
const THREE=await import('three');
const runTest=test;test=async(name,fn)=>{if(!input.only||input.only.includes(name))return runTest(name,fn);};
function mutate(source,url){
 if(!input.mutation)return source;
 const gen=url===file('static/twin/twin_generator.js'),roof=url===file('static/twin/twin_roof.js');
 let changed=source;
 if(gen){
  if(input.mutation==='merge_barrier')changed=source.replace(' || p.userData.supportedRoof','');
  if(input.mutation==='per_roof_batches')changed=source.replaceAll('supportedLevels.has(level.id)','supportedLevels.has(entry.indices[0])')
   .replaceAll('supportedLevels.set(level.id, group)','supportedLevels.set(entry.indices[0], group)').replaceAll('supportedLevels.get(level.id)','supportedLevels.get(entry.indices[0])');
  if(input.mutation==='missing_level_fallback')changed=source.replace('isSupported(section) ? first','isSupported(section) ? ordered.at(-1)');
  if(input.mutation==='original_shell_index')changed=source.replace('`roof:${indices[index]}`','`roof:${index}`');
  if(input.mutation==='original_gable_index')changed=source.replace('`roof:${sectionIndices[gable.section]}`','`roof:${gable.section}`');
  if(input.mutation==='fascia_bounds')changed=source.replace('const rect = roofBounds(section);',
   'const rect = section.rect.map((v,i)=>v+(i<2?-1:1)*(section.overhang||0));');
  if(input.mutation==='gutter_owner_ranges')changed=source.replace('if (gutterGeo.userData.snapRanges) gMesh.userData.snapRanges = gutterGeo.userData.snapRanges;','');
  if(input.mutation==='gutter_bake_kind')changed=source.replace(/(cur\.ranges\.push\(\{[^;]*?)surfaceKind:\s*'gutter'/,
   '$1surfaceKind: undefined');
 }
 if(roof){
  if(input.mutation==='uncut_height_cap')changed=source.replace('|| cuts(section, index).some(poly => insidePolygon(poly, x, y))','');
  if(input.mutation==='every_floor_cuts')changed=source.replace(/return levels\.filter\(level => level\.elevation - 0\.8 <= high \+ EPS[\s\S]*?\)\.flatMap\(level => polygons\.get\(level\.id\) \|\| \[\]\);/,
   'return levels.flatMap(level => polygons.get(level.id) || []);');
  if(input.mutation==='ghost_height_cap')changed=source.replace(" || ['ghost', 'proposal'].includes(section.state)",'');
  if(input.mutation==='underside_floor_guard')changed=source.replace('z - thickness <= floor + EPS','z <= floor + EPS');
  if(input.mutation==='supported_gables')changed=source.replace('    if (isSupported(section)) return;','');
 }
 if(changed!==source)console.log('MUTATION_APPLIED '+input.mutation);
 return changed;
}
registerHooks({load(url,ctx,next){let result=next(url,ctx);
 if(url===file('static/twin/twin_generator.js')||url===file('static/twin/twin_roof.js'))result={...result,source:mutate(String(result.source),url)};
 if(url===file('static/twin/twin_generator.js')){
  const source=String(result.source),anchor='  for (const g of mergeGroups) batch(';
  assert.ok(source.includes(anchor),'pre-batch observation point');
  const finalAnchor='  groups.gableCut.visible = false;',at=source.lastIndexOf(finalAnchor);
  assert.ok(at>source.indexOf(anchor),'post-batch observer follows the final real merge');
  const observed=source.slice(0,at)+'  globalThis.__awningBatchedCapture?.(root);\n'+source.slice(at);
  return {...result,source:observed.replace(anchor,'  globalThis.__awningCapture?.(root);\n'+anchor)};
 }return result;
}});
const G=await import(file('static/twin/twin_generator.js'));
const R=await import(file('static/twin/twin_roof.js'));
const {createSkyCover,writeWeatherOpen}=await import(file('static/twin/sky/sky_cover.js'));
const {atlasMesh,prepareReceivers}=await import(file('static/twin/bake/atlas.js'));
const {bakeSource}=await import(file('static/twin/bake/source.js'));
const {createPieceVisibility}=await import(file('static/twin/twin_visibility.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const {releaseBakeSource}=await import(file('static/twin/bake/source.js'));
const clone=structuredClone;
const rect=(a,b,c,d)=>[[a,b],[c,b],[c,d],[a,d]];
const hash=a=>a?createHash('sha256').update(new Uint8Array(a.buffer,a.byteOffset,a.byteLength)).digest('hex'):null;
const attr=a=>a?[a.itemSize,a.normalized,hash(a.array)]:null;
const material=m=>[m.name,m.userData.materialKey??null,m.transparent,m.alphaTest,m.opacity,m.side,m.depthWrite,m.depthTest,m.color?.getHexString()??null];
const geometry=g=>[...['position','normal','uv'].map(k=>attr(g.attributes[k])),attr(g.index)];
const row=m=>({piece:m.userData.pieceId,kind:m.userData.kind,part:m.userData.part??m.userData.bakePart??'',
 layer:m.layers.mask,material:material(m.material),geometry:geometry(m.geometry),matrix:m.matrixWorld.elements,
 triangles:(m.geometry.index?.count??m.geometry.attributes.position.count)/3,
 bounds:[0,1,2].map(axis=>{const values=m.geometry.attributes.position.array.filter((_,i)=>i%3===axis);return [Math.min(...values),Math.max(...values)];}),
 height:[Math.min(...m.geometry.attributes.position.array.filter((_,i)=>i%3===1)),
  Math.max(...m.geometry.attributes.position.array.filter((_,i)=>i%3===1))],
 level:(()=>{for(let p=m.parent;p;p=p.parent)if(p.userData.levelKey)return p.userData.levelKey;return null;})()});
function section(id,bounds,plate=8,extra={}){return {id,roof:id,kind:'gable',ridge:'x',pitch:4,
 rect:bounds,plate,overhang:1,level:'L1',plane_edges:{y0:0,x1:1,y1:2,x0:3},...extra};}
function fixture(){const outline=rect(0,0,32,16);
 return {materials:{ceiling:{id:'paint'}},site:{},buildings:[{id:'b',base:0,position:[0,0],rotation:0,
 levels:[{id:'L1',elevation:0,ceiling:8,outline}],
 rooms:[{id:'room',level:'L1',polygon:outline,state:'settled',ceiling_material:{id:'paint'}}],
 walls:outline.map((from,i)=>({id:'w'+i,from,to:outline[(i+1)%4],level:'L1',height:8,thickness:.5,exterior:true,state:'settled'})),
 openings:[],roof:{sections:[section('left',[0,0,20,16]),section('right',[20,0,32,16],9)],extensions:[],flags:[]},roofs:[],
 porches:[{id:'porch',polygon:rect(8,-6,24,0),floor:0,columns:[{at:[9,-.5],size:.5},{at:[23,-.5],size:.5}]}],
 lights:[{id:'lamp',level:'L1',at:[12,2],room:'room',color:'#fff1dd',intensity:1}],fixtures:[],stairs:[],items:[],anchors:[]}]};}
function kit(){return {materials:Object.fromEntries(['floor','patio_concrete','siding','interior_wall','roof','trim',
 'window_frame','door','porch_ceiling','base','lattice','counter','stainless','lawn','paving','ceiling'].map(k=>[k,{asset:k,color:'#bbccee'}])),
 manifest:{red:{kind:'material',household:true,revision:1,maps:{},params:{tint:'#cc4422'}},blue:{kind:'material',household:true,revision:1,maps:{},params:{tint:'#2255cc'}}}};}
function awning(plate=7,extra={}){return section('awning',[8,-6,24,3],plate,{kind:'shed',low_side:'y0',pitch:2,
 support:{kind:'bracket'},host:{wall:'w0',edge:2},...extra});}
function add(p,s=awning()){p.buildings[0].roof.sections.splice(1,0,s);return p;}
async function build(p,options={}){let raw=[],batched=[];
 globalThis.__awningCapture=root=>{root.updateMatrixWorld(true);root.traverse(m=>{if(m.isMesh)raw.push(row(m));});};
 globalThis.__awningBatchedCapture=root=>{root.updateMatrixWorld(true);root.traverse(m=>{if(m.isMesh)batched.push({
  row:row(m),owners:(m.userData.snapRanges||[]).map(r=>r.pieceId)});});};
 const out=G.buildTwin(clone(p),kit(),'high',{viewing:true,...options});await out.ready;
 globalThis.__awningCapture=undefined;globalThis.__awningBatchedCapture=undefined;
 out.root.updateMatrixWorld(true);return {out,raw,batched};}
function dispose(b){releaseBakeSource(b.out.root);disposeObject(b.out.root);}
const selected=(b,predicate)=>b.raw.filter(predicate);
const structural=b=>selected(b,m=>!['awning','awning-up'].includes(m.piece)
 &&m.kind!=='light'&&!(m.piece==='porch'&&(['column','screen'].includes(m.part)||m.layer===2**31)));
function costs(b){let meshes=0,draws=0,triangles=0;
 const supportedIds=new Set([...b.out.roofSurfaces.values()].flatMap(env=>env.sections.flatMap((s,i)=>
  s.support?.kind&&s.support.kind!=='walls'?[s.id||`roof:${i}`]:[])));
 b.out.root.traverseVisible(m=>{if(!m.isMesh||m.layers.isEnabled(31))return;
  const materials=Array.isArray(m.material)?m.material:[m.material];if(!materials.some(x=>x.visible))return;
  meshes++;draws+=Array.isArray(m.material)?m.geometry.groups.filter(g=>m.material[g.materialIndex]?.visible).length:1;
  triangles+=(m.geometry.index?.count??m.geometry.attributes.position.count)/3*(m.isInstancedMesh?m.count:1);
 });return {meshes,draws,triangles,unmerged_meshes:b.raw.filter(m=>m.layer!==2**31).length,
 supported_triangles:b.raw.filter(m=>m.layer!==2**31&&supportedIds.has(m.piece)).reduce((n,m)=>n+m.triangles,0)};}
async function pair(p,s=awning()){const without=await build(p),withRoof=await build(add(clone(p),s));return [without,withRoof];}
function surface(b,ids){const env=b.out.roofSurfaces.get('b'),out=[];
 for(let i=0;i<env.section.length;i++)if(ids.includes(env.sections[env.section[i]]?.id))
  out.push([env.sections[env.section[i]].id,env.side[i],env.edge[i],Array.from(env.positions.slice(i*9,i*9+9))]);
 return out;}
function same(a,b,predicate,label){assert.deepEqual(selected(b,predicate),selected(a,predicate),label);}

await test('mixed_indices_wall_tops_gables_steps_and_trim_are_byte_identical',async()=>{
 const p=fixture();p.buildings[0].roof.sections[0].materials={roof:{id:'red'}};
 p.buildings[0].roof.sections[1].materials={roof:{id:'blue'}};
 const [a,b]=await pair(p,awning(24));
 same(a,b,m=>m.kind==='wall'||['left','right'].includes(m.piece),'wall tops, gable and step geometry, trim, materials and roof picks');
 assert.ok(b.raw.some(m=>m.piece==='awning'&&m.layer!==2**31),'supported slab draws');
 assert.deepEqual(surface(b,['left','right']),surface(a,['left','right']),'roofSurfaces labels address original section identity');
 assert.ok(b.out.roofSurfaces.get('b').sections.some(s=>s.id==='awning'));
 dispose(a);dispose(b);
});
await test('ceilings_floors_lights_and_porch_posts_ignore_supported_roof',async()=>{
 const [a,b]=await pair(fixture(),awning(24));
 same(a,b,m=>!['awning','left','right'].includes(m.piece),'all other piece buffers including floors, ceilings, porch columns and fixtures');
 assert.deepEqual(b.out.roomLights.map(l=>l.position.toArray()),a.out.roomLights.map(l=>l.position.toArray()),'room lamp heights');
 assert.ok(a.raw.some(m=>m.part==='ceiling'),'fixture includes a ceiling');
 assert.ok(a.raw.some(m=>m.part==='column'),'fixture includes a porch column');dispose(a);dispose(b);
});
await test('supported_roof_under_or_over_walled_roof_keeps_every_walled_buffer',async()=>{
 for(const plate of [5,24]){const [a,b]=await pair(fixture(),awning(plate));
  assert.deepEqual(structural(b),structural(a),'independence at plate '+plate);
  const own=b.raw.filter(m=>m.piece==='awning'&&m.layer!==2**31);
  assert.ok(own.length>=3,'slab, soffit, fascia draw separately before batching');
  assert.ok(own.some(m=>m.part.startsWith('roof-plane:awning:')),'covering has its plane identity');
  dispose(a);dispose(b);
 }
});
await test('supported_pick_keeps_roof_piece_and_plane_part_identity',async()=>{
 const b=await build(add(fixture()));const proxy=b.out.pickObjects.get('b:awning');
 assert.ok(proxy,'roof pick exists');assert.equal(proxy.userData.kind,'roof');assert.equal(proxy.userData.pieceId,'awning');
 assert.ok(proxy.geometry.attributes.position.count>0,'supported proxy has actual roof geometry');
 const parts=proxy.userData.partObjects||[];
 assert.ok(parts.some(p=>(p.object.userData.part||'').startsWith('roof-plane:awning:')),'pick retains per-plane part geometry');dispose(b);
});
await test('supported_roof_floor_cutters_include_storeys_that_reach_the_slab',async()=>{
 const p=fixture(),s=awning(6);const b=await build(add(p,s)),env=b.out.roofSurfaces.get('b');let own=0;
 for(let t=0;t<env.section.length;t++)if(env.sections[env.section[t]].id==='awning'){
  own++;const p=Array.from(env.positions.slice(t*9,t*9+9));
  const x=(p[0]+p[3]+p[6])/3,y=(p[1]+p[4]+p[7])/3;
  assert.ok(!(x>0&&x<32&&y>0&&y<16),'supported triangle cannot cover any occupied floor outline');
 }
 assert.ok(own>0,'exterior roof portion survives');dispose(b);
});
await test('two_storeys_awnings_use_stored_floor_visibility',async()=>{
 const p=fixture(),b=p.buildings[0],outline=rect(0,0,16,16);
 b.levels.push({id:'L2',elevation:9,ceiling:8,outline});
 b.rooms.push({id:'upstairs',level:'L2',polygon:outline,ceiling_material:{id:'paint'}});
 b.walls.push(...outline.map((from,i)=>({id:'upw'+i,from,to:outline[(i+1)%4],level:'L2',height:8,thickness:.5,exterior:true})));
 b.roof.sections[0].plate=17;b.roof.sections[0].level='L2';
 const baseline=await build(p);
 add(p,awning(25,{level:'L1'}));b.roof.sections.push(awning(5,{id:'awning-up',roof:'awning-up',level:'L2'}));
 const built=await build(p);const low=built.out.pickObjects.get('b:awning'),up=built.out.pickObjects.get('b:awning-up');
 assert.deepEqual(structural(built),structural(baseline),'both floors retain wall, walled-roof, ceiling and floor mesh buffers');
 const levelOf=m=>{for(let p=m.parent;p;p=p.parent)if(p.userData.levelKey)return p.userData.levelKey;return null;};
 assert.equal(levelOf(low),'b:L1','high physical roof remains owned by its stored L1');
 assert.equal(levelOf(up),'b:L2','low physical roof remains owned by its stored L2');
 for(const [id,expected] of [['awning','b:L1'],['awning-up','b:L2']])
  assert.ok(built.raw.filter(m=>m.piece===id).every(m=>m.level===expected),'all own meshes share stored level');
 for(const [visible,wanted] of [['b:L1','awning'],['b:L2','awning-up']]){
  for(const [key,group] of Object.entries(built.out.groups.levels))group.visible=key===visible;
  const picks=[];built.out.root.traverseVisible(o=>{if(o===low||o===up)picks.push(o.userData.pieceId);});
  assert.deepEqual(picks,[wanted],'floor-view group toggling exposes only the matching awning');
 }
 dispose(baseline);dispose(built);
});
await test('free_standing_supported_roof_draws_without_walls',async()=>{
 const p=fixture(),b=p.buildings[0];b.walls=[];b.rooms=[];b.porches=[];b.lights=[];
 b.levels=[{id:'L1',elevation:0,ceiling:8}];b.roof.sections=[awning(8,{support:{kind:'post'},host:undefined})];
 const built=await build(p);assert.ok(built.raw.filter(m=>m.piece==='awning'&&m.layer!==2**31).length>=3);
 assert.ok(built.out.pickObjects.get('b:awning').geometry.attributes.position.count>0);dispose(built);
});
await test('per_edge_overhang_changes_only_its_physical_bound',()=>{
 const s=section('edge',[0,0,20,10],8,{edges:[{overhang_ft:0},{overhang_ft:2},{overhang_ft:3},{overhang_ft:.5}]});
 assert.equal(R.sectionHeight(s,10,-.1),null,'host edge has zero overhang');
 assert.notEqual(R.sectionHeight(s,21.9,5),null);assert.equal(R.sectionHeight(s,22.1,5),null);
 assert.notEqual(R.sectionHeight(s,10,12.9),null);assert.equal(R.sectionHeight(s,10,13.1),null);
 assert.notEqual(R.sectionHeight(s,-.4,5),null);assert.equal(R.sectionHeight(s,-.6,5),null);
});
await test('pure_roof_groups_do_not_create_supported_gables_or_steps',()=>{
 const w=section('w',[0,0,20,10]),s=section('s',[5,-4,15,5],12,{support:{kind:'brace'}});
 assert.equal(R.roofMesh([s]).gables.length,0,'supported roofs have no wall gable fills');
 assert.deepEqual(R.stepFaces([w,s]),R.stepFaces([w]),'no step siding against a supported roof');
});
await test('nearest_roof_above_floor_ignores_roofs_below_the_floor',()=>{
 const sections=[section('below',[0,0,20,10],2,{kind:'flat'}),
  section('high',[0,0,20,10],20,{kind:'flat'}),section('near',[0,0,20,10],8,{kind:'flat'})];
 assert.equal(R.lowestRoofAbove(sections,5,5,3),8);
 assert.equal(R.lowestRoofAbove(sections,5,5,9),20);
 assert.equal(R.lowestRoofAbove(sections,5,5,20),null);
 assert.equal(R.lowestRoofAbove(sections,50,50,0),null);
});
await test('grouped_mesh_retains_original_indices_and_independent_envelopes',()=>{
 const a=section('first',[0,0,20,10]),s=awning(30,{rect:[0,0,20,10]}),
  b=section('last',[25,0,35,10]);
 const rows=mesh=>Array.from(mesh.section,(index,t)=>[index,mesh.side[t],mesh.edge[t],
  Array.from(mesh.positions.slice(t*9,t*9+9))]);
 const combined=R.roofMeshGroups([a,s,b]),expected=R.roofMesh([a,b]);
 assert.deepEqual(rows(combined).filter(r=>r[0]!==1),rows(expected).map(r=>[r[0]===0?0:2,...r.slice(1)]));
 assert.deepEqual(rows(combined).filter(r=>r[0]===1),rows(R.roofMesh([s])).map(r=>[1,...r.slice(1)]));
 assert.deepEqual(R.roofMeshGroups([a,b]),expected,'no-supported path retains exact original mesh shape');
});
await test('fixture_reports_supported_roof_cost_with_existing_materials',async()=>{
 const [a,b]=await pair(fixture());const before=costs(a),after=costs(b);
 const materials=build=>new Set(build.raw.filter(m=>m.layer!==2**31).map(m=>JSON.stringify(m.material)));
 const original=materials(a);assert.ok([...materials(b)].every(m=>original.has(m)),'same existing material keys and flags');
 assert.ok(after.triangles>before.triangles,'a roof adds its own slab triangles');
 const delta=Object.fromEntries(Object.keys(before).map(k=>[k,after[k]-before[k]]));
 assert.ok(delta.draws<=3,'one same-material supported level costs at most three draws');
 console.log('AWNING_FIXTURE_COST '+JSON.stringify({before,after,delta,
  weather_receiver_triangle_delta:delta.triangles-delta.supported_triangles}));dispose(a);dispose(b);
});
await test('generated_cached_cover_keeps_supported_roof_outside_floor_outlines',async()=>{
 const p=add(fixture()),built=await build(p),cached=createSkyCover(p,built.out.roofSurfaces),fallback=createSkyCover(p);
 const x=12*.3048,z=4*.3048,y=.2;
 assert.equal(fallback.open(x,y,z),0,'fallback roof covers this outdoor point');
 assert.equal(cached.open(x,y,z),fallback.open(x,y,z),'generated cached cover includes supported roof');
 assert.ok(Math.abs(cached.roofHeight(x,y,z)-fallback.roofHeight(x,y,z))<1e-5,'drawn and fallback eave planes agree');
 assert.equal(built.out.skyCover.open(x,y,z),0,'buildTwin exposes the complete cover to consumers');dispose(built);
});
await test('cached_supported_cover_shelters_actual_weather_receiver_vertices',async()=>{
 const p=add(fixture()),built=await build(p),cover=createSkyCover(p,built.out.roofSurfaces);
 const root=new THREE.Group(),receiver=new THREE.Mesh(new THREE.PlaneGeometry(.2,.2).rotateX(-Math.PI/2),new THREE.MeshStandardMaterial());
 receiver.position.set(12*.3048,.2,4*.3048);root.add(receiver);writeWeatherOpen(root,cover);
 assert.ok(receiver.geometry.attributes.weatherOpen,'real receiver gets weather exposure');
 assert.ok(Array.from(receiver.geometry.attributes.weatherOpen.array).every(v=>v===0),'under-awning outdoor receiver is dry');
 receiver.geometry.dispose();receiver.material.dispose();dispose(built);
});
await test('supported_slab_soffit_fascia_are_ordinary_bake_receivers_and_shadow_casters',async()=>{
 const p=add(fixture()),built=await build(p),owns=m=>(m.userData.snapRanges||[]).some(r=>r.pieceId==='awning');
 const own=[];built.out.root.traverse(m=>{if(m.isMesh&&owns(m))own.push(m);});
 assert.ok(own.length>0,'drawn supported material batches retain ownership');
 assert.ok(own.every(m=>m.receiveShadow&&m.castShadow&&atlasMesh(m)),'all opaque roof batches cast and receive ordinary light');
 const receivers=prepareReceivers(bakeSource(built.out.root),p).filter(owns);
 assert.ok(receivers.length>0,'actual neutral bake preparation retains supported roof receivers');
 assert.ok(receivers.every(m=>!m.geometry.userData.bakeExcluded&&m.geometry.attributes.position.count>0),'supported receiving geometry is included');
 dispose(built);
});
await test('supported_overlap_cannot_clip_a_walled_step_face',()=>{
 const a=section('a',[0,0,10,10],10,{kind:'flat'}),b=section('b',[10,0,20,10],8,{kind:'flat'}),
  s=awning(30,{rect:[5,2,15,6],kind:'flat'});
 assert.deepEqual(R.stepFaces([a,b,s]),R.stepFaces([a,b]),'even third-party covering tests exclude supported roofs');
});
await test('settled_supported_meshes_keep_their_own_material_batch_domain',async()=>{
 const [a,b]=await pair(fixture(),awning(24));
 assert.ok(a.batched.length>0&&b.batched.length>0,'both real post-batch snapshots contain meshes');
 assert.ok(b.batched.some(({owners})=>owners.includes('awning')),'post-batch ownership assertion runs on supported batches');
 // Observe after the actual material merge, before weather exposure splits
 // outdoor horizontal triangles along the new awning's drip line. That later
 // receiver tessellation legitimately changes when a surface gains shelter.
 const rows=built=>built.batched.filter(({row,owners})=>{
  if(row.layer===2**31)return false;
  if(owners.includes('awning')){assert.ok(owners.every(id=>id==='awning'),'supported slab cannot merge into existing level meshes');return false;}
  return true;
 }).map(({row})=>JSON.stringify(row)).sort();
 assert.deepEqual(rows(b),rows(a),'every non-own material batch remains byte-identical after merging');
 const finalRows=built=>{const result=[];built.out.root.traverse(m=>{
  if(!m.isMesh||m.layers.isEnabled(31)||(m.userData.snapRanges||[]).some(r=>r.pieceId==='awning'))return;
  // This porch receiver alone gains a new outdoor drip line. Its generated
  // slab was compared above; its changed weather exposure is tested separately.
  if(m.material.name==='patio_concrete')return;
  result.push(JSON.stringify(row(m)));
 });return result.sort();};
 assert.deepEqual(finalRows(b),finalRows(a),'final drawn walls, walled roofs, gables, steps and trim remain byte-identical');
 dispose(a);dispose(b);
});
await test('supported_solar_panels_follow_the_roof_stored_floor',async()=>{
 const p=add(fixture(),awning(7,{kind:'flat',pitch:0,level:'L2'}));
 p.buildings[0].levels.push({id:'L2',elevation:9,ceiling:8,outline:rect(0,0,32,16)});
 p.buildings[0].solar_zones=[{id:'solar-awning',roof:'awning',plane:[0,0,7],rect:[10,-5,16,-2],
  panel_width:1,panel_height:1,gap:.1,setback:0,count:2,state:'settled'}];
 const built=await build(p),own=built.raw.filter(m=>m.piece==='solar-awning');
 assert.ok(own.length>0,'solar panels are generated on their own supported plane');
 assert.ok(own.every(m=>m.level==='b:L2'),'solar panel meshes and pick share their roof level');dispose(built);
});
await test('supported_gutters_follow_the_roof_stored_floor',async()=>{
 const p=add(fixture(),awning(7,{level:'L2',gutters:{y0:true}}));
 p.buildings[0].levels.push({id:'L2',elevation:9,ceiling:8,outline:rect(0,0,32,16)});
 const built=await build(p),gutters=built.raw.filter(m=>m.part==='gutter');
 assert.ok(gutters.length>0,'fixture generates a supported gutter');
 assert.ok(gutters.every(m=>m.level==='b:L2'),'supported gutter geometry shows only on its roof stored floor');dispose(built);
});
function heightFixture(){const p=fixture(),b=p.buildings[0];b.levels[0].ceiling=30;
 b.roof.sections=[section('left',[0,-8,32,16],10,{kind:'flat'}),section('right',[0,-8,32,16],20,{kind:'flat'})];
 b.porches[0].screened=true;
 b.lights=[{id:'lamp',level:'L1',at:[12,-3],room:'room'},
  {id:'porch-lamp',level:'L1',at:[16,-3],room:'Porch'},
  {id:'uncovered-lamp',level:'L1',at:[30,-3],room:'room'}];return p;}
const lampHeights=b=>Object.fromEntries(b.out.roomLights.map(l=>[l.userData.pieceId,l.position.y]));
let pinnedBaselineGenerator;
await test('overlapping_walled_roofs_keep_0ec59a62_upper_roof_and_porch_light_baselines',async()=>{
 const urls=new Map(),paths=Object.keys(input.baselineSources);
 for(const [path,original] of Object.entries(input.baselineSources)){
  const source=original.replace(/((?:from|import)\s*['"])(\.[^'"]+)(['"])/g,(_,a,s,b)=>{
   const url=new URL(s,file(path)).href,ref=paths.find(p=>file(p)===url);
   return a+(ref?'awning-baseline:'+ref:url)+b;
  });urls.set(path,'data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 }
 registerHooks({resolve(spec,ctx,next){return spec.startsWith('awning-baseline:')
  ?{url:urls.get(spec.slice(16)),shortCircuit:true}:next(spec,ctx);}});
 const baseline=await import(urls.get('static/twin/twin_generator.js')),p=heightFixture(),current=await build(p);
 pinnedBaselineGenerator=baseline;
 const old=baseline.buildTwin(clone(p),kit(),'high',{viewing:true});await old.ready;old.root.updateMatrixWorld(true);
 const rows=root=>{const out=[];root.traverse(m=>{if(m.isMesh)out.push(JSON.stringify(row(m)));});return out.sort();};
 assert.deepEqual(lampHeights(current),Object.fromEntries(old.roomLights.map(l=>[l.userData.pieceId,l.position.y])),
  'both room and special porch-light heights remain exact baseline');
 assert.deepEqual(rows(current.out.root),rows(old.root),'all drawn and picking buffers retain 0ec59a62 bytes with overlapping walled roofs');
 dispose(current);dispose({out:old});
});
await test('lower_supported_underside_caps_actual_porch_columns_and_screens',async()=>{
 const p=heightFixture();p.buildings[0].porches[0].polygon=rect(8,-6,24,-.25);
 const [a,b]=await pair(p,awning(6,{kind:'flat',pitch:0})),expected=6-G.ROOF_THICKNESS;
 const before=a.raw.filter(m=>m.piece==='porch'&&m.layer!==2**31&&['column','screen'].includes(m.part)),
  after=b.raw.filter(m=>m.piece==='porch'&&m.layer!==2**31&&['column','screen'].includes(m.part));
 assert.ok(before.some(m=>m.part==='column')&&before.some(m=>m.part==='screen'),'actual columns and screens generated');
 assert.ok(before.every(m=>m.height[1]>expected+1),'walled baseline is above supported roof');
 assert.ok(after.every(m=>Math.abs(m.height[1]-expected)<1e-5),'each actual column and screen ends at supported underside');
 assert.deepEqual(structural(b),structural(a),'walls, walled roofs, ceilings and floors retain buffers');dispose(a);dispose(b);
});
await test('lower_supported_underside_caps_room_and_porch_lights_only_where_covered',async()=>{
 const [a,b]=await pair(heightFixture(),awning(6,{kind:'flat',pitch:0})),old=lampHeights(a),now=lampHeights(b),expected=6-G.ROOF_THICKNESS;
 assert.equal(now.lamp,expected,'room light uses supported underside');
 assert.equal(now['porch-lamp'],expected,'special fixed porch-light baseline also accepts lower underside');
 assert.equal(now['uncovered-lamp'],old['uncovered-lamp'],'uncovered light keeps exact baseline');dispose(a);dispose(b);
});
await test('supported_height_override_ignores_below_floor_and_above_baseline_roofs',async()=>{
 const p=heightFixture(),base=await build(p);
 for(const plate of [-2,40]){const built=await build(add(clone(p),awning(plate,{kind:'flat',pitch:0})));
  assert.deepEqual(lampHeights(built),lampHeights(base),'light baseline unchanged for roof '+plate);
  same(base,built,m=>m.piece==='porch','porch baseline unchanged for roof '+plate);dispose(built);
 }dispose(base);
});
await test('lowest_valid_supported_underside_wins_with_a_taller_supported_roof_present',async()=>{
 const p=heightFixture();add(p,awning(7,{kind:'flat',pitch:0}));
 p.buildings[0].roof.sections.push(awning(5,{id:'awning-up',roof:'awning-up',kind:'flat',pitch:0}));
 const built=await build(p),heights=lampHeights(built);
 assert.equal(heights.lamp,5-G.ROOF_THICKNESS);assert.equal(heights['porch-lamp'],5-G.ROOF_THICKNESS);dispose(built);
});
await test('supported_height_override_checks_actual_raised_porch_floor',async()=>{
 const p=heightFixture();p.buildings[0].porches[0].floor=4;
 const [a,b]=await pair(p,awning(2,{kind:'flat',pitch:0}));
 same(a,b,m=>m.piece==='porch','roof below raised porch floor does not cap columns or screens');dispose(a);dispose(b);
});
await test('supported_light_override_checks_room_and_porch_room_floor_offsets',async()=>{
 const p=heightFixture(),house=p.buildings[0];house.rooms[0].floor_offset_ft=3;
 house.lights[0].at=[12,2];house.rooms.push({id:'porch-room',kind:'porch',level:'L1',
  polygon:clone(house.porches[0].polygon),floor_offset_ft:3,state:'settled'});
 const [a,b]=await pair(p,awning(2,{kind:'flat',pitch:0,rect:[8,-6,24,6]}));
 assert.deepEqual(lampHeights(b),lampHeights(a),'roof below either actual raised room floor does not cap its light');
 same(a,b,m=>m.piece==='porch','porch-room floor offset also protects its column and screen heights');dispose(a);dispose(b);
});
for(const kind of ['flat','shed'])await test('cut_host_overhang_cannot_lower_an_indoor_lamp_or_recessed_porch_post_'+kind,async()=>{
 const p=fixture(),house=p.buildings[0];house.lights[0].at=[12,.5];house.porches[0].columns=[{at:[9,.6],size:.5}];
 const [a,b]=await pair(p,awning(6,{kind,pitch:kind==='flat'?0:2,rect:[8,-4,24,0]}));
 const mesh=b.out.roofSurfaces.get('b');
 for(const at of [[12,.5],[9,.6]]){let covered=false;
  for(let t=0;t<mesh.section.length;t++)if(mesh.sections[mesh.section[t]].id==='awning'){
   const q=Array.from(mesh.positions.slice(t*9,t*9+9)),tri=[0,3,6].map(i=>[q[i],q[i+1]]);
   const signs=tri.map((u,i)=>{const v=tri[(i+1)%3];return (v[0]-u[0])*(at[1]-u[1])-(v[1]-u[1])*(at[0]-u[0]);});
   if(signs.every(v=>v>=-1e-7)||signs.every(v=>v<=1e-7))covered=true;
  }
  assert.equal(covered,false,'indoor lamp/post sample has no drawn '+kind+' awning triangle');
 }
 assert.deepEqual(lampHeights(b),lampHeights(a),'cut-away roof cannot cap indoor lamp');
 same(a,b,m=>m.piece==='porch','cut-away roof cannot cap recessed post or change its proxy');
 const old=pinnedBaselineGenerator.buildTwin(clone(p),kit(),'high',{viewing:true});await old.ready;old.root.updateMatrixWorld(true);
 const drawn=root=>{const rows=[];root.traverse(m=>{if(m.isMesh)rows.push(JSON.stringify(row(m)));});return rows.sort();};
 assert.deepEqual(drawn(a.out.root),drawn(old.root),'indoor-lamp/recessed-post fixture without support retains every 0ec59a62 mesh and pick buffer');
 assert.deepEqual(lampHeights(a),Object.fromEntries(old.roomLights.map(l=>[l.userData.pieceId,l.position.y])),
  'unchanged indoor lamp retains pinned 0ec59a62 height');dispose({out:old});dispose(a);dispose(b);
});
await test('upper_storey_awning_over_lower_wing_retains_drawn_slab_and_pick',async()=>{
 const p=fixture(),b=p.buildings[0],upper=rect(0,0,16,16);b.porches=[];b.lights=[];
 b.levels.push({id:'L2',elevation:9,ceiling:8,outline:upper});
 b.rooms.push({id:'upstairs',level:'L2',polygon:upper,ceiling_material:{id:'paint'}});
 b.roof.sections[0].rect=[0,0,16,16];b.roof.sections[0].plate=17;b.roof.sections[0].level='L2';
 b.roof.sections[1].rect=[16,0,32,16];b.roof.sections[1].plate=8;
 b.roof.sections.splice(1,0,awning(14,{id:'upper-awning',roof:'upper-awning',kind:'flat',pitch:0,level:'L2',rect:[14,2,24,10]}));
 b.roof.sections.push(awning(6,{id:'lower-awning',roof:'lower-awning',kind:'flat',pitch:0,rect:[24,-4,30,0]}));
 const built=await build(p);
 for(const id of ['upper-awning','lower-awning']){
  assert.ok(built.raw.some(m=>m.piece===id&&m.layer!==2**31),'supported slab draws: '+id);
  assert.ok(built.out.pickObjects.get('b:'+id)?.geometry.attributes.position.count>0,'supported slab is selectable: '+id);
 }
 const mesh=built.out.roofSurfaces.get('b');let upperWing=false;
 for(let t=0;t<mesh.section.length;t++)if(mesh.sections[mesh.section[t]].id==='upper-awning'){
  const q=Array.from(mesh.positions.slice(t*9,t*9+9)),x=(q[0]+q[3]+q[6])/3,y=(q[1]+q[4]+q[7])/3;
  assert.ok(x>=16-1e-6,'upper occupied volume cuts only its actual outline');if(x>17&&y>2&&y<10)upperWing=true;
 }
 assert.ok(upperWing,'awning stands above lower wing floor instead of being erased');dispose(built);
});
function manyAwnings(count,levelCount,gutters=false){const p=fixture(),b=p.buildings[0];b.porches=[];b.lights=[];
 if(levelCount===2)b.levels.push({id:'L2',elevation:9,ceiling:8,outline:rect(0,0,32,16)});
 const ids=[];for(let level=0;level<levelCount;level++)for(let i=0;i<count;i++){
  const id=`shade-${level}-${i}`;ids.push(id);b.roof.sections.push(awning(7+level*9,{id,roof:id,kind:'flat',pitch:0,
   level:'L'+(level+1),rect:[2+i*9,-8,8+i*9,-4],...(gutters?{gutters:{y0:true}}:{})}));
 }return {p,ids};}
function supportedDrawsPerLevel(built,ids){const result=Object.fromEntries(Object.keys(built.out.groups.levels).map(k=>[k,0]));
 built.out.root.traverseVisible(m=>{if(!m.isMesh||m.layers.isEnabled(31)||!(m.userData.snapRanges||[]).some(r=>ids.includes(r.pieceId)))return;
  const level=row(m).level;assert.ok(level,'supported draw has an owning level');
  result[level]=(result[level]||0)+(Array.isArray(m.material)?m.geometry.groups.length:1);
 });return result;}
await test('one_two_three_awnings_share_three_draws_per_building_level',async()=>{
 for(const gutters of [false,true])for(const levels of [1,2])for(const count of [1,2,3]){
  const {p,ids}=manyAwnings(count,levels,gutters),base=clone(p);base.buildings[0].roof.sections=base.buildings[0].roof.sections.filter(s=>!s.support);
  const a=await build(base),b=await build(p),before=costs(a),after=costs(b),delta=after.draws-before.draws,perLevel=supportedDrawsPerLevel(b,ids);
  assert.ok(delta<=3*levels,`${count} awnings on ${levels} levels cost ${delta}, expected at most ${3*levels} draws`);
  for(const [level,draws] of Object.entries(perLevel))assert.ok(draws>0&&draws<=3,`${level} owns ${draws} supported draws, expected 1..3`);
  console.log('AWNING_LEVEL_COST '+JSON.stringify({count,levels,gutters,before,after,delta_draws:delta,per_level_draws:perLevel}));
  assert.ok(b.batched.length>0,'nonempty real post-batch snapshot');
  for(const id of ids){assert.ok(b.out.pickObjects.get('b:'+id)?.geometry.attributes.position.count>0,'each shared-batch roof retains own pick');
   assert.ok(b.batched.some(({owners})=>owners.includes(id)),'shared material range retains roof owner '+id);}
  dispose(a);dispose(b);
 }
});
await test('levels_without_awnings_have_zero_supported_draws',async()=>{
 for(const target of ['L1','L2']){
  const {p,ids}=manyAwnings(3,2);p.buildings[0].roof.sections=p.buildings[0].roof.sections.filter(s=>!s.support||s.level===target);
  const remaining=ids.filter(id=>id.startsWith('shade-'+(target==='L1'?0:1)+'-')),built=await build(p),perLevel=supportedDrawsPerLevel(built,remaining);
  assert.ok(perLevel['b:'+target]>0&&perLevel['b:'+target]<=3,'occupied awning floor has at most three draws');
  assert.equal(perLevel['b:'+(target==='L1'?'L2':'L1')],0,'floor without an awning adds no supported draw');dispose(built);
 }
});
await test('shared_batches_hide_and_pick_each_roof_without_altering_its_neighbours',async()=>{
 const {p,ids}=manyAwnings(3,2),built=await build(p),visibility=createPieceVisibility();
 const ranges=()=>{const found=[];built.out.root.traverse(m=>{if(!m.isMesh||m.layers.isEnabled(31))return;
  for(const range of m.userData.snapRanges||[])if(ids.includes(range.pieceId))found.push({mesh:m,range});});return found;};
 const entries=ranges();assert.ok(entries.length>0,'shared supported material ranges exist');
 const digest=({mesh,range})=>hash(mesh.geometry.attributes.position.array.slice(range.start*3,(range.start+range.count)*3));
 const initial=entries.map(digest);
 for(const id of ids){visibility.set([id],[]);visibility.apply(built.out.root);
  assert.equal(built.out.pickObjects.get('b:'+id).visible,false,'hidden owner pick suppressed');
  entries.forEach((entry,i)=>{if(entry.range.pieceId!==id)assert.equal(digest(entry),initial[i],'neighbour owner range remains byte-identical');});
  assert.ok(entries.some(entry=>entry.range.pieceId===id&&(()=>{const a=entry.mesh.geometry.attributes.position.array,
   start=entry.range.start*3,end=(entry.range.start+entry.range.count)*3;
   for(let i=start+3;i<end;i++)if(a[i]!==a[start+(i-start)%3])return false;return true;})()),'hidden supported triangles collapse');
  visibility.restore();assert.ok(built.out.pickObjects.get('b:'+id).visible,'restored roof remains pickable');
  entries.forEach((entry,i)=>assert.equal(digest(entry),initial[i],'range restore returns exact original bytes'));
 }
 const receivers=prepareReceivers(bakeSource(built.out.root),p),received=new Set(receivers.flatMap(m=>(m.userData.snapRanges||[]).map(r=>r.pieceId)));
 for(const id of ids)assert.ok(received.has(id),'neutral bake retains every shared owner '+id);dispose(built);
});
await test('guttered_awnings_share_level_draws_and_keep_per_roof_gutter_ranges',async()=>{
 const {p,ids}=manyAwnings(3,2,true),base=clone(p);base.buildings[0].roof.sections=base.buildings[0].roof.sections.filter(s=>!s.support);
 const a=await build(base),b=await build(p),delta=costs(b).draws-costs(a).draws;
 assert.ok(delta<=6,'three guttered awnings on each of two levels cost at most three draws per level');
 const gutters=[];b.out.root.traverse(m=>{if(m.isMesh)for(const r of m.userData.snapRanges||[])if(r.surfaceKind==='gutter'||r.part==='gutter')gutters.push({mesh:m,range:r});});
 for(const id of ids)assert.ok(gutters.some(({range})=>range.pieceId===id),'gutter range carries its individual roof id '+id);
 const visibility=createPieceVisibility(),digest=({mesh,range})=>hash(mesh.geometry.attributes.position.array.slice(range.start*3,(range.start+range.count)*3)),original=gutters.map(digest);
 for(const id of ids){visibility.set([id],[]);visibility.apply(b.out.root);
  gutters.forEach((entry,i)=>{if(entry.range.pieceId!==id)assert.equal(digest(entry),original[i],'hiding one gutter preserves neighbouring gutter bytes');
   else{const a=entry.mesh.geometry.attributes.position.array,start=entry.range.start*3,end=(entry.range.start+entry.range.count)*3;
    for(let j=start+3;j<end;j++)assert.equal(a[j],a[start+(j-start)%3],'hidden gutter triangles collapse with their owning roof');}});
  visibility.restore();gutters.forEach((entry,i)=>assert.equal(digest(entry),original[i],'gutter range restores exactly'));
 }
 const receivers=prepareReceivers(bakeSource(b.out.root),p);
 assert.ok(receivers.some(m=>(m.geometry.userData.gutterFaceRanges||[]).some(r=>r.count>0)),
  'actual neutral receiver preparation recognizes gutter faces inside shared trim batches');
 assert.ok(gutters.every(({range})=>range.surfaceKind==='gutter'),'shared gutter ranges retain their bake/weather surface classification');
 assert.ok(gutters.every(({range})=>range.bakePart==='gutter'),'shared gutter ranges retain their gutter bake part');
 dispose(a);dispose(b);
});
await test('index_zero_middle_last_and_idless_gable_hip_roofs_keep_original_names_and_bytes',async()=>{
 for(const idless of [false,true])for(const kind of ['gable','hip'])for(const at of [0,1,2]){
  const p=fixture();p.buildings[0].porches=[];p.buildings[0].lights=[];
  p.buildings[0].roof.sections.forEach((s,i)=>{s.materials={roof:{id:i?'blue':'red'}};if(idless){delete s.id;delete s.roof;}});
  const a=await build(p),mixed=clone(p);mixed.buildings[0].roof.sections.splice(at,0,awning(24,{kind,ridge:'y'}));
  const b=await build(mixed);
  for(let i=0;i<2;i++){
   const oldId=idless?'roof:'+i:['left','right'][i],newId=idless?'roof:'+(i+(i>=at?1:0)):oldId;
   const normalize=r=>({...r,piece:'walled',part:r.part.replace(/roof-plane:roof:\d+:/,'roof-plane:walled:')});
   assert.deepEqual(a.raw.filter(m=>m.piece===oldId).map(normalize),b.raw.filter(m=>m.piece===newId).map(normalize),
    `kind=${kind},insert=${at},idless=${idless}: walled material and geometry`);
   assert.ok(b.out.pickObjects.has('b:'+newId),'original-index fallback roof name remains selectable '+newId);
  }dispose(a);dispose(b);
 }
});
await test('per_edge_overhang_places_actual_fascia_on_each_overridden_boundary',async()=>{
 const p=fixture();p.buildings[0].porches=[];p.buildings[0].lights=[];
 add(p,awning(6,{kind:'flat',pitch:0,rect:[40,-8,50,-2],edges:[{overhang_ft:0},{overhang_ft:2},{overhang_ft:3},{overhang_ft:.5}]}));
 const built=await build(p),fascia=built.raw.filter(m=>m.piece==='awning'&&m.layer!==2**31&&m.material[0]==='trim');
 assert.ok(fascia.length>0,'actual fascia uses the existing trim material');
 const lo=axis=>Math.min(...fascia.map(m=>m.bounds[axis][0])),hi=axis=>Math.max(...fascia.map(m=>m.bounds[axis][1]));
 assert.ok(Math.abs(lo(0)-39.49)<1e-4&&Math.abs(hi(0)-52.01)<1e-4,'left/right fascia follows independent overhangs');
 assert.ok(Math.abs(lo(2)+1.01)<1e-4&&Math.abs(hi(2)-8.01)<1e-4,'host/opposite fascia follows independent overhangs');dispose(built);
});
await test('missing_supported_level_defaults_to_first_floor_visibility_and_material',async()=>{
 const p=fixture(),b=p.buildings[0];b.levels[0].materials={roof:{id:'red'}};
 b.levels.push({id:'L2',elevation:9,ceiling:8,outline:rect(0,0,16,16),materials:{roof:{id:'blue'}}});
 const s=awning(25);delete s.level;add(p,s);const built=await build(p),own=built.raw.filter(m=>m.piece==='awning');
 assert.ok(own.length>0&&own.every(m=>m.level==='b:L1'),'missing stored level belongs to first floor');
 const explicit=clone(p);explicit.buildings[0].roof.sections.find(s=>s.id==='awning').level='L1';const reference=await build(explicit);
 assert.deepEqual(own,reference.raw.filter(m=>m.piece==='awning'),'missing level uses exact first-floor materials and pick geometry');
 explicit.buildings[0].roof.sections.find(s=>s.id==='awning').level='L2';const upper=await build(explicit);
 assert.notDeepEqual(own.filter(m=>m.part.startsWith('roof-plane:')).map(m=>m.material),
  upper.raw.filter(m=>m.piece==='awning'&&m.part.startsWith('roof-plane:')).map(m=>m.material),
  'fixture resolves visually distinct first- and upper-floor roof finishes');dispose(upper);dispose(reference);dispose(built);
});
await test('ghost_proposal_and_sub_thickness_roofs_cannot_cap_real_posts_or_lamps',async()=>{
 const p=heightFixture(),a=await build(p);
 for(const extra of [{state:'ghost'},{state:'proposal'},{plate:.1}]){
  const s=awning(extra.plate??6,{kind:'flat',pitch:0,...extra}),b=await build(add(clone(p),s));
  assert.deepEqual(lampHeights(b),lampHeights(a),'nonphysical or below-floor underside cannot cap lights');
  same(a,b,m=>m.piece==='porch','nonphysical or below-floor underside cannot invert real columns');dispose(b);
 }dispose(a);
});
finish();
"""


MUTATIONS = {
    'merge_barrier': ['settled_supported_meshes_keep_their_own_material_batch_domain'],
    'per_roof_batches': ['one_two_three_awnings_share_three_draws_per_building_level'],
    'uncut_height_cap': ['overlapping_walled_roofs_keep_0ec59a62_upper_roof_and_porch_light_baselines',
                         'cut_host_overhang_cannot_lower_an_indoor_lamp_or_recessed_porch_post_flat',
                         'cut_host_overhang_cannot_lower_an_indoor_lamp_or_recessed_porch_post_shed'],
    'every_floor_cuts': ['upper_storey_awning_over_lower_wing_retains_drawn_slab_and_pick'],
    'missing_level_fallback': ['missing_supported_level_defaults_to_first_floor_visibility_and_material'],
    'original_shell_index': ['index_zero_middle_last_and_idless_gable_hip_roofs_keep_original_names_and_bytes'],
    'original_gable_index': ['index_zero_middle_last_and_idless_gable_hip_roofs_keep_original_names_and_bytes'],
    'fascia_bounds': ['per_edge_overhang_places_actual_fascia_on_each_overridden_boundary'],
    'ghost_height_cap': ['ghost_proposal_and_sub_thickness_roofs_cannot_cap_real_posts_or_lamps'],
    'underside_floor_guard': ['ghost_proposal_and_sub_thickness_roofs_cannot_cap_real_posts_or_lamps'],
    'supported_gables': ['pure_roof_groups_do_not_create_supported_gables_or_steps'],
    'gutter_owner_ranges': ['guttered_awnings_share_level_draws_and_keep_per_roof_gutter_ranges'],
    'gutter_bake_kind': ['guttered_awnings_share_level_draws_and_keep_per_roof_gutter_ranges'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mutations', action='store_true', help='Remove each fix in memory and prove its runtime test fails')
    parser.add_argument('--mutation', choices=MUTATIONS, help='Rerun one mutation while preserving the other saved results')
    parser.add_argument('--only', action='append', help='Run one named runtime proof (repeatable)')
    args = parser.parse_args()
    payload = {'root': ROOT.as_posix(), 'baselineSources': baseline_sources()}
    if args.only:
        payload['only'] = args.only
    if args.mutations or args.mutation:
        directory = ROOT.parent / '.superpowers' / 'sdd' / 'awnings'
        rows = []
        selected = {args.mutation: MUTATIONS[args.mutation]} if args.mutation else MUTATIONS
        for mutation, tests in selected.items():
            code, output = run_node(DRIVER, {**payload, 'mutation': mutation, 'only': tests}, timeout=300)
            failures = re.findall(r'^\s*FAIL\s+(\S+)', output, re.MULTILINE)
            row = {'mutation': mutation, 'exit': code, 'applied': f'MUTATION_APPLIED {mutation}' in output,
                   'failures': failures, 'killed': code not in (None, 0) and bool(failures)}
            row['killed'] = row['killed'] and row['applied']
            rows.append(row)
            (directory / f'task-3-fix1-mutation-{mutation}.log').write_text(output, encoding='utf-8')
            print(json.dumps(row), flush=True)
        results_path = directory / 'task-3-fix1-generator-mutations.json'
        saved = {row['mutation']: row for row in json.loads(results_path.read_text(encoding='utf-8'))} if args.mutation and results_path.exists() else {}
        saved.update((row['mutation'], row) for row in rows)
        results_path.write_text(json.dumps(list(saved.values()), indent=2), encoding='utf-8')
        return int(not all(row['killed'] for row in rows))
    code, output = run_node(DRIVER, payload, timeout=300)
    print(output.strip())
    return 1 if code is None else code


if __name__ == '__main__':
    sys.exit(main())
