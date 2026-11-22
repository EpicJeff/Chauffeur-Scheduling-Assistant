"""Mounted editor/viewer neutral bake-source parity, without a browser."""
import json
from pathlib import Path
import sys
from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node
import test_twin_baker_js as B
ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX.replace("url.startsWith('file:') && url.endsWith('.js')", "url.startsWith('file:') && url.endsWith('.js') && !/basis/i.test(url)") + r"""
import {createRequire} from 'node:module';
const THREE = await import('three');
Object.assign(Renderer.prototype,{getDrawingBufferSize:v=>v.set(1440,900),getViewport:v=>v.set(0,0,1440,900),setViewport(){},getScissor:v=>v.set(0,0,1440,900),setScissor(){},getScissorTest:()=>false,setScissorTest(){}});
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {atlasJob}=await import(file('static/twin/bake/atlas_transport.js'));
const {bakeSource,isBakeRoot}=await import(file('static/twin/bake/source.js'));
const {materialParts}=await import(file('static/twin/bake/bindings.js'));
const {createBaker,bakeLayout,encodePage,decodePage}=await import(file('static/twin/bake/baker.js'));
const host=editor=>{const h=new Element();if(editor){const shell=new Element();shell.className='editor-shell';shell.append(h);}return h;};
location.search='?test=1';
globalThis.fetch=async()=>new Promise(()=>{});
const plan=input.plan, kit=input.kit;
plan.site ||= {};plan.site.hardscape ||= [];plan.site.hardscape.push({id:'bake-editor-pad',polygon:[[0,0],[10,0],[10,10],[0,10]],material:'concrete'});
const layout={room:{density:1,page:256,gutter:2}};
const viewer=await mountTwin(host(false),{plan:structuredClone(plan),kit,tier:'high',bake:true});
const editor=await mountTwin(host(true),{plan:structuredClone(plan),kit,tier:'high',bake:true});
let vr,er,v,e;
const roots=()=>{vr=viewer.scene.children.find(isBakeRoot);er=editor.scene.children.find(isBakeRoot);assert.ok(vr&&er);};
try {
 await test('editor_and_viewer_share_atlas_key_and_charts',()=>{
  roots();v=buildAtlas(vr,viewer.plan,layout);e=buildAtlas(er,editor.plan,layout);
  assert.equal(e.key,v.key);assert.equal(e.room.charts.length,v.room.charts.length);
  const walls=e.room.charts.filter(c=>c.mesh.material.name==='interior_wall');
  assert.ok(walls.length);assert.ok(walls.every(c=>materialParts(c).length),'editor walls receive the neutral charts');
  console.log('  key '+e.key+' charts '+e.room.charts.length);
 });
 await test('focused_finished_selected_scene_excludes_editor_layers',async()=>{
  const building=editor.plan.buildings.find(b=>b.id===input.pool),wall=building.walls[0];
  const edited=structuredClone(editor.plan);edited.buildings.find(b=>b.id===input.pool).walls[0].faces={left:{color:'#445566'},right:{color:'#445566'}};
  await viewer.rebuild(structuredClone(edited));await editor.rebuild(edited);
  editor.showAnchors=true;
  await editor.setEditableLevel(input.pool+':L1');
  editor.setSelection({selected:{kind:'wall',id:wall.id,building:input.pool},members:[{kind:'wall',pieceId:wall.id,buildingId:input.pool}]});
  while(!editor.ready)await new Promise(setImmediate);
  editor.setSelection({selected:null,members:[],room:{building:input.pool,level:'L1',id:input.kitchen,allowed:[input.kitchen],walls:[]}});
  while(!editor.ready)await new Promise(setImmediate);
  roots();
  for(const name of ['ghost-piece','sheet','handle','selection-outline','proposal-preview']){
   const layer=new THREE.Mesh(new THREE.BoxGeometry(100,100,100),new THREE.MeshStandardMaterial({name:'interior_wall'}));
   layer.name=name;layer.userData.ghost=name==='ghost-piece';er.add(layer);
  }
  const source=bakeSource(er);
  for(const name of ['ghost-piece','sheet','handle','selection-outline','proposal-preview'])assert.equal(source.getObjectByName(name),undefined);
  const baseline=atlasJob(vr,viewer.plan,layout),job=atlasJob(er,editor.plan,layout);
  assert.equal(job.cacheKey,baseline.cacheKey,'worker atlas jobs also match');
  v=buildAtlas(vr,viewer.plan,layout);e=buildAtlas(er,editor.plan,layout);
  assert.equal(e.key,v.key);assert.equal(e.room.charts.length,v.room.charts.length);
  const walls=e.room.charts.filter(c=>c.mesh.material.name==='interior_wall');
  assert.ok(walls.every(c=>materialParts(c).length),'focused walls still bind');
 });
 await test('cancelled_handle_preview_keeps_the_same_manual_controller',()=>{
  const controller=editor.bake,authored=editor.plan,building=authored.buildings.find(b=>b.id===input.pool);
  const preview=structuredClone(authored);preview.buildings.find(b=>b.id===input.pool).walls[0].to[0]+=.25;
  editor.rebuildLevel(input.pool,'L1',preview,{walls:[building.walls[0].id]});
  assert.equal(editor.bake,controller);assert.equal(controller.active(),true,'preview does not cancel the bake');
  editor.rebuildLevel(input.pool,'L1',structuredClone(authored),{walls:[building.walls[0].id]});
  editor.syncBake();assert.equal(editor.bake,controller,'cancel restores without a restart');
 });
 await test('mounted_editor_bakes_the_same_light_as_viewer',async()=>{
  const job=input, B={encodePage,decodePage};
"""
DRIVER += B.DRIVER[B.DRIVER.index("// --- the fake GPU"):B.DRIVER.index("// --- the house, the lights")]
DRIVER += B.DRIVER[B.DRIVER.index("const building ="):B.DRIVER.index("async function setup")]
DRIVER += r"""
  const require=createRequire(import.meta.url),quiet={print(){},printErr(){}};
  const E=await require(input.root+'/static/vendor/basis-universal/basis_encoder.js')({...quiet,wasmBinary:readFileSync(input.root+'/static/vendor/basis-universal/basis_encoder.wasm')});E.initializeBasis();
  const T=await require(input.root+'/static/vendor/three-r187/addons/libs/basis/basis_transcoder.js')({...quiet,wasmBinary:readFileSync(input.root+'/static/vendor/three-r187/addons/libs/basis/basis_transcoder.wasm')});T.initializeBasis();
  const codec={encode:async j=>encodePage(E,j),decode:async bytes=>decodePage(T,bytes)},server=fakeServer({leaseRequired:true});
  const vp=bakeLayout(v,layout,[k1]),ep=bakeLayout(e,layout,[k1]);
  assert.deepEqual(ep.entries,vp.entries,'selection tint and the focused scene cannot change physical light freshness');
  const original=editor.bake,renderer=fakeRenderer();
  editor.bake={idle:async()=>{},occlusionRoot:()=>e.sourceRoot};
  try {
   const baker=createBaker(editor,{renderer,atlas:e,layout,lights:[k1],api:server.api,codec,owner:'editor'});
   assert.equal(await baker.bakeNext(),k1.device);assert.ok(renderer.log.renders>0);
   assert.equal(server.manifests.get(e.key).lights[k1.device].key,ep.entries[k1.device].key);
   assert.ok(server.pages.size);assert.deepEqual(server.bad,[]);
  }finally{editor.bake=original;}
 });
} finally {editor.dispose();viewer.dispose();}
finish();
"""
if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    fixture=json.loads((ROOT/'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit=json.loads((ROOT/'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'));kit['manifest']={}
    code,out=run_node(DRIVER,{'root':ROOT.as_posix(),'plan':B.household_pool_house(),'kit':kit,'pool':B.POOL,'kitchen':B.KITCHEN,'hall':B.HALL,'changing':B.CHANGING},timeout=240)
    print(out);sys.exit(code or 0)
