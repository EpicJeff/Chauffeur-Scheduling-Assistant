"""Model-record refreshes use ordinary mounted-view building/yard retention."""
import sys
from pathlib import Path
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const T=await import('three');
window.location={href:'http://house.test/house/editor'};
globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {rememberImport,modelAssetKey}=await import(file('static/twin/twin_library.js'));
const {beginEdit}=await import(file('static/twin/edit_timing.js'));
const {YARD_PARTS,buildYard,yardPartKeys}=await import(file('static/twin/twin_yard.js'));
const {GLTFLoader}=await import('three/addons/loaders/GLTFLoader.js');
const load=GLTFLoader.prototype.loadAsync;
GLTFLoader.prototype.loadAsync=async()=>({scene:new T.Group().add(new T.Mesh(new T.BoxGeometry(),new T.MeshStandardMaterial()))});
const square=(x,y,w=12)=>[[x,y],[x+w,y],[x+w,y+w],[x,y+w]];
const building=(id,x)=>({id,position:[x,0],base:0,levels:[{id:'L1',elevation:0,ceiling:8,outline:square(0,0)}],
 walls:square(0,0).map((from,i,a)=>({id:'w'+i,level:'L1',from,to:a[(i+1)%4],height:8,thickness:.5,exterior:true,state:'settled'})),
 rooms:[{id:'r',level:'L1',polygon:square(0,0),state:'settled'}],openings:[],items:[],anchors:[],roof:{sections:[],flags:[]}});
for(const consumer of ['item','opening','furniture','planting'])await test(`ordinary_rebuild_after_record_edit_${consumer}`,async()=>{
 const asset='import-retention-'+consumer;
 const record={id:asset,revision:1,kind:'furniture',model:'original.glb',files:{'original.glb':true},parts:[],materials:{}};
 rememberImport(record);
 const p={buildings:[building('used',0),building('unused',40)],materials:{},site:{lot:square(-10,-10,80),
  furniture:[],planting:[],fence:[{id:'f',polyline:[[0,-5],[10,-5]],height:3}],
  pool:{id:'pool',polygon:square(20,20,5),depth:4,coping:1}}};
 if(consumer==='item')p.buildings[0].items=[{id:'copy',asset,host:{floor:'r',u:.5,v:.5}}];
 if(consumer==='opening')p.buildings[0].openings=[{id:'door',model:asset,kind:'door',wall:'w0',level:'L1',at:4,width:3,sill:0,head:7,state:'settled'}];
 // Always place furniture too: a record can be shared by house and yard.
 p.site.furniture=[{id:'yard',asset,at:[15,15]}];
 if(consumer==='planting')p.site.planting=[{id:'plant',asset,at:[17,17]}];
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await mountTwin(host,{plan:p,kit:{materials:{},manifest:{}},tier:'low',bake:false});
 try{
  const a=view.groups.levels['used:L1'],b=view.groups.levels['unused:L1'],yard=view.scene.getObjectByName('yard');
  const parts=Object.fromEntries(YARD_PARTS.map(name=>[name,yard.children.filter(o=>o.userData.yardPart===name)]));
  let carRefreshes=0;view.cars={draw(){},stop(){},update(){carRefreshes++;}};
  rememberImport({...record,revision:2,materials:{Wood:{material:'oak'}}});
  const timing=beginEdit({op:'model-record'});await view.rebuild(p,{timing});
  assert.equal(carRefreshes,1,'record refresh reaches the retained live-car layer even with the same plan object');
  const houseUse=['item','opening'].includes(consumer);
  assert.deepEqual(timing.buildings_rebuilt,houseUse?['used']:[]);
  assert.deepEqual(timing.buildings_reused,houseUse?['unused']:['used','unused']);
  assert.equal(view.groups.levels['unused:L1'],b);
  if(houseUse)assert.notEqual(view.groups.levels['used:L1'],a);else assert.equal(view.groups.levels['used:L1'],a);
  assert.deepEqual(timing.yard_reused_parts,[...YARD_PARTS].filter(n=>n!=='furniture'));
  const next=view.scene.getObjectByName('yard');
  for(const name of YARD_PARTS)if(name!=='furniture')assert.deepEqual(next.children.filter(o=>o.userData.yardPart===name),parts[name],name);
  assert.notEqual(next.children.find(o=>o.userData.yardPart==='furniture'),parts.furniture[0]);
 }finally{view.dispose();}
});
for(const imported of [true,false])await test(`low_yard_kind_change_${imported?'import_rebuilds_only_furniture':'builtin_retains_every_part'}`,async()=>{
 const id=imported?'import-heavy-kind-retention':'builtin-kind-retention';
 const record={id,revision:1,kind:'furniture',model:'original.glb',files:{'original.glb':true},size:[2,1,4],triangles:400000};
 const kit={materials:{},manifest:imported?{}:{[id]:record}};
 if(imported)rememberImport(record);
 const p={buildings:[],materials:{},site:{lot:square(-10,-10,40),
  furniture:[{id:'yard-kind',asset:id,at:[0,0]}],fence:[{id:'f',polyline:[[0,-5],[10,-5]],height:3}],
  pool:{id:'pool',polygon:square(20,20,5),depth:4,coping:1}}};
 const nativeFetch=globalThis.fetch;let first;
 try{
  if(!imported)globalThis.fetch=async()=>new Response('',{status:404}); // Exercise the built-in manifest fallback.
  first=(await buildYard(p,kit,'low',{viewing:true})).group;
 }finally{globalThis.fetch=nativeFetch;}
 const objects=name=>first.children.filter(o=>o.userData.yardPart===name);
 const parts=Object.fromEntries(YARD_PARTS.map(name=>[name,objects(name)]));
 assert.ok(parts.furniture.length&&parts.fences.length&&parts.pool.length,'real furniture and sibling parts render');
 const before=yardPartKeys(p,kit,'low',{viewing:true}),assetKey=JSON.stringify(modelAssetKey(id,kit));
 const glyphs=g=>g.children.filter(o=>o.userData.yardPart==='furniture'&&[].concat(o.material||[]).some(m=>m.map?.image?.width===192));
 assert.equal(glyphs(first).length,0);
 // Hold revision and every other field fixed so kind itself must invalidate imports.
 if(imported)rememberImport({...record,kind:'car'});else record.kind='car';
 const after=yardPartKeys(p,kit,'low',{viewing:true});
 assert.deepEqual(YARD_PARTS.filter(name=>before[name]!==after[name]),imported?['furniture']:[]);
 if(imported)assert.notEqual(JSON.stringify(modelAssetKey(id,kit)),assetKey);
 else assert.equal(JSON.stringify(modelAssetKey(id,kit)),assetKey,'built-in key stays byte-identical');
 const next=(await buildYard(p,kit,'low',{viewing:true,previous:first,materials:new Map(first.userData.materials)})).group;
 next.userData.adoptParts();
 assert.deepEqual(next.userData.yardRebuiltParts,imported?['furniture']:[]);
 assert.deepEqual(next.userData.yardReusedParts,YARD_PARTS.filter(name=>!imported||name!=='furniture'));
 for(const name of YARD_PARTS){
  const current=next.children.filter(o=>o.userData.yardPart===name);
  if(imported&&name==='furniture')assert.ok(current.every(o=>!parts[name].includes(o)),'furniture objects rebuild');
  else assert.deepEqual(current,parts[name],name+' retains exact objects');
 }
 assert.equal(glyphs(next).length,imported?1:0,'heavy import kind selects the car glyph');
 next.userData.releasePlants();
});
GLTFLoader.prototype.loadAsync=load;finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=90)
    print(output)
    sys.exit(code)
