"""Saved copy part changes through the editor's real mounted-view settle path."""
import json
from pathlib import Path
import sys

from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const T = await import('three');
globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
window.location = {href:'http://house.test/house/editor?tier=high'};
globalThis.ProgressEvent = class {constructor(type, values) {Object.assign(this, values);}};
globalThis.FileReader = class {
 readAsArrayBuffer(blob) {blob.arrayBuffer().then(value => {this.result=value;this.onloadend?.();});}
};
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {rememberImport} = await import(file('static/twin/twin_library.js'));
const {stampParts} = await import(file('static/twin/model_levels.js'));
const {beginEdit} = await import(file('static/twin/edit_timing.js'));
const {GLTFExporter} = await import('three/addons/exporters/GLTFExporter.js');
const source = new T.Group();
for (const [i, name] of ['Wood', '', 'Wood', 'Glass'].entries()) {
 const geometry = new T.BoxGeometry(.3,.4,.2);
 if (i === 1) geometry.deleteAttribute('uv');
 const material = new T.MeshStandardMaterial({name, color:'#c8a070',
  transparent:name==='Glass', opacity:name==='Glass'?.4:1});
 const mesh = new T.Mesh(geometry, material);mesh.position.x=i*.5;source.add(mesh);
}
const parts = stampParts(source);
assert.deepEqual(parts.map(p=>p.key), ['Wood','unnamed','Wood~2','Glass']);
const bytes = await new GLTFExporter().parseAsync(source, {binary:true});
const nativeFetch = globalThis.fetch;
globalThis.fetch = async (url, opts) => {
 const path=String(url?.url || url);
 if (/^(data:|blob:)/.test(path)) return nativeFetch(url,opts);
 if (path.endsWith('.glb')) return new Response(bytes);
 if (path.endsWith('/materials/manifest')) return new Response(JSON.stringify({revision:0,entries:{}}));
 return new Response('[]',{headers:{'Content-Type':'application/json'}});
};
// Only external texture I/O is doubled; material resolution and GLB loading are real.
T.TextureLoader.prototype.load = function(url, done) {
 const texture = new T.DataTexture(new Uint8Array([160,100,50,255]),1,1);
 texture.name=String(url);queueMicrotask(()=>done?.(texture));return texture;
};
const materials = (view, id, part='Wood') => {
 const found = new Set();
 view.scene.traverse(o => {
  if (!o.isMesh || !o.userData.snapRanges?.some(r=>r.pieceId===id && r.partKey===part)) return;
  for (const m of [].concat(o.material)) found.add(m);
 });
 assert.ok(found.size, `rendered ${id}/${part} has snap ranges`);
 return [...found];
};
const check = (view,id,overridden) => {
 for (const m of materials(view,id)) {
  if (overridden) {
   assert.equal(m.userData.materialId || m.userData.bakeMaterialId, 'wood_planks', `${id} renders the saved override`);
   assert.ok(m.map, `${id} has the library texture`);
  } else {
   assert.equal(m.color.getHexString(), 'c8a070', `${id} returns to authored colour`);
   assert.equal(m.map, null, `${id} returns to authored untextured material`);
  }
 }
};
for (const [consumer, method] of [['item','settle'],['opening','settle'],['furniture','settle'],['item','rebuild']])
await test(`${consumer}_copy_material_${method}`, async () => {
 const asset=`import-copy-render-${consumer}-${method}`;
 let record={id:asset,revision:1,kind:consumer==='opening'?'door':'furniture',
  model:'original.glb',files:{'original.glb':true},parts,parts_version:1,materials:{}};
 rememberImport(record);
 let plan=structuredClone(input.plan);
 const house=plan.buildings.find(b=>b.rooms.some(r=>r.state!=='ghost'));
 const room=house.rooms.find(r=>r.state!=='ghost');
 house.items=[];
 let target;
 if (consumer==='item') {
  house.items=[{id:'copy',asset,state:'settled',host:{floor:room.id,u:.3,v:.5}},
   {id:'sibling',asset,state:'settled',host:{floor:room.id,u:.7,v:.5}}];
  target=p=>p.buildings.find(b=>b.id===house.id).items[0];
 } else if (consumer==='opening') {
  const wall=house.walls.find(w=>w.level===room.level && w.state!=='ghost');
  const make=(id,at)=>({id,model:asset,kind:'door',wall:wall.id,level:wall.level,
   at,width:3,sill:0,head:7,state:'settled'});
  house.openings=[make('copy',3),make('sibling',8)];
  target=p=>p.buildings.find(b=>b.id===house.id).openings[0];
 } else {
  plan.site.furniture=[{id:'copy',asset,at:[10,10]},{id:'sibling',asset,at:[15,10]}];
  target=p=>p.site.furniture[0];
 }
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
 const view=await mountTwin(host,{plan,kit:input.kit,tier:'high',bake:false});
 const untouchedId=plan.buildings.find(b=>b.id!==house.id)?.id;
 const untouched=()=>Object.entries(view.groups.levels).filter(([k])=>k.startsWith(untouchedId+':'));
 const kept=untouched();
 const update=async entries=>{
  const next=structuredClone(plan);
  if(entries===null)delete target(next).model_materials;else target(next).model_materials=entries;
  // editor.js::settleView calls settle after the authoritative server plan arrives.
  const timing=beginEdit({op:'set_object'});
  const result=await view[method](next,{selection:{buildingId:house.id,pieceId:'copy'},timing});
  while(view.yardSettling)await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(view.yardError,null);
  console.log(`${consumer}/${method}: ${result?.path||'rebuild'}, rebuilt=${JSON.stringify(timing.buildings_rebuilt||[])}`);
  assert.deepEqual(timing.buildings_rebuilt || [], consumer==='furniture'?[]:[house.id]);
  assert.deepEqual(untouched(),kept,'unaffected building groups retain exact objects');
  plan=next;
 };
 try {
  check(view,'copy',false);check(view,'sibling',false);
  await update({Wood:{material:'wood_planks',texture:'real'}});
  check(view,'copy',true);check(view,'sibling',false);
  for(const part of ['unnamed','Wood~2','Glass'])for(const m of materials(view,'copy',part))assert.equal(m.map,null);
  await update({});check(view,'copy',false);
  // "The model (all copies)" refreshes the record with the same plan object.
  record={...record,revision:2,materials:{Wood:{material:'wood_planks',texture:'real'}}};
  rememberImport(record);await view.rebuild(plan);
  check(view,'copy',true);check(view,'sibling',true);
  await update({Wood:{material:'original'}});
  check(view,'copy',false);check(view,'sibling',true);
  await update(null);check(view,'copy',true);check(view,'sibling',true);
 } finally {view.dispose();}
});
finish();
"""

if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text())
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text())
    manifest = json.loads((ROOT / 'twin_library/manifest.json').read_text())
    kit['manifest'] = {'wood_planks': manifest['wood_planks']}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(),
        'plan': flatten(assemble(fixture)[0]), 'kit': kit}, timeout=180)
    print(output)
    sys.exit(code)
