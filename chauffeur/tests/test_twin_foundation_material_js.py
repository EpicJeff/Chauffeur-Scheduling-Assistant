"""Production house slab generator, bake/reuse keys and shared shelf under Node."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const slotListeners=new Set();let selectedMaterial=null;
const library={selected:()=>selectedMaterial,onSelect:fn=>{slotListeners.add(fn);return()=>slotListeners.delete(fn);},reveal:async()=>{}};
async function useMaterial(slot,id){selectedMaterial={kind:'material',id,name:id};for(const fn of slotListeners)fn();await click(slot.querySelector('[data-slot-use]'));}

const THREE=await import(three);
THREE.TextureLoader.prototype.load=function(url,done){const texture=new THREE.Texture({width:32,height:32});queueMicrotask(()=>done(texture));return texture;};
const {buildTwin,buildingKey}=await import(file('static/twin/twin_generator.js'));
const {materialSlot,offsetSurfaceUvs}=await import(file('static/twin/twin_library.js'));
const {atlasJob}=await import(file('static/twin/bake/atlas_transport.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {foundationShelf}=await import(file('static/twin/editor/foundation_shelf.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const square=[[0,0],[10,0],[10,8],[0,8]],ref={id:'red_brick_03',color:'#aa3322'};
const b={id:'b',name:'House',position:[0,0],rotation:0,base:2,foundation:{mode:'fixed',offset_ft:0,thickness_ft:1},
 levels:[{id:'L1',elevation:0,ceiling:8,outline:square},{id:'L2',elevation:8,ceiling:8,outline:square}],
 walls:[],rooms:[],openings:[],roof:{sections:[]},stairs:[],anchors:[],items:[]};
const plan={units:'ft',materials:{},buildings:[b],site:{terraces:[]}};
const build=async(p=plan,kit=input.kit,tier='low',previous)=>{const out=buildTwin(p,kit,tier,{viewing:true,previous});await out.ready;return out;};
const slabs=out=>{const found=[];out.root.traverse(o=>{
 if(o.isMesh&&!o.layers.isEnabled(31)&&o.geometry.attributes.position){
  o.geometry.computeBoundingBox();if(o.geometry.boundingBox.min.y<-.5)found.push(o);
 }
});return found;};
const slabPositions=mesh=>{const p=mesh.geometry.attributes.position,ids=mesh.geometry.index?.array||Array.from({length:p.count},(_,i)=>i),out=[];
 for(let i=0;i<ids.length;i+=3){const triangle=Array.from(ids.slice(i,i+3));if(triangle.some(j=>p.getY(j)<-.5))
  out.push(...triangle.flatMap(j=>[p.getX(j),p.getY(j),p.getZ(j)]));}return out;};
const slabUvs=mesh=>{const {position:p,uv}=mesh.geometry.attributes,ids=mesh.geometry.index?.array||Array.from({length:p.count},(_,i)=>i),out=[];
 for(let i=0;i<ids.length;i+=3){const triangle=Array.from(ids.slice(i,i+3));if(triangle.some(j=>p.getY(j)<-.5))
  out.push(...triangle.flatMap(j=>[uv.getX(j),uv.getY(j)]));}return out;};
const appearance=o=>[o.material.name,o.material.color.getHexString(),o.material.roughness,o.material.metalness,
 [...o.geometry.attributes.position.array],[...o.geometry.attributes.uv.array]];
const byText=(root,text)=>root.querySelectorAll('button').find(n=>textOf(n)===text);
globalThis.fetch=async()=>({ok:true,text:async()=>JSON.stringify({materials:[{id:ref.id,name:'Brick',color:'#aa3322'}],items:[]})});
function shelf({locked=false,foundation=b.foundation}={}){
 const p=structuredClone(plan);p.buildings[0].foundation=structuredClone(foundation);
 const sent=[],errors=[],previews=[],host=document.createElement('div');document.body.append(host);
 foundationShelf(host,p.buildings[0],{getPlan:()=>p,getKit:()=>input.kit,library,canEdit:()=>!locked,
  queue:work=>Promise.resolve().then(work),op:async o=>{sent.push(o);p.buildings[0].foundation=structuredClone(o.foundation);},
  report:e=>errors.push(e.message),preview:async p=>previews.push(p)});
 return {p,host,sent,errors,previews};
}
await test('generator_chosen_and_empty_material_geometry_and_lowest_floor',async()=>{
 const plain=await build();assert.ok(slabs(plain).length);
 assert.ok(slabs(plain).every(m=>m.material.name==='patio_concrete'&&'#'+m.material.color.getHexString()===input.kit.materials.patio_concrete.color));
 for(const materials of [undefined,{}, {slab:null},{slab:ref}]){
  const p=structuredClone(plan);if(materials!==undefined)p.buildings[0].foundation.materials=materials;
  const out=await build(p),meshes=slabs(out);assert.equal(meshes.length,slabs(plain).length);
  for(const [i,mesh]of meshes.entries()){
   assert.equal(mesh.parent.userData.levelKey,'b:L1');
   assert.deepEqual(slabPositions(mesh),slabPositions(slabs(plain)[i]),'foundation positions survive material batching');
   if(materials?.slab){assert.equal(mesh.material.color.getHexString(),'aa3322');
    const expected=materialSlot(ref,'patio_concrete',input.kit,'low',new Map(),()=>{throw Error('unexpected default');});
    assert.equal(mesh.material.name,expected.name);assert.equal(mesh.material.map?.repeat.x,expected.map?.repeat.x);
   }else assert.deepEqual(appearance(mesh),appearance(slabs(plain)[i]));
  }
 }
 const p=structuredClone(plan);p.buildings[0].materials={siding:{id:ref.id,color:'#ff0000'},interior_wall:ref};
 assert.deepEqual(slabs(await build(p)).map(appearance),slabs(plain).map(appearance));
});
await test('household_tint_uv_scale_offset_and_live_revision',async()=>{
 const kit=structuredClone(input.kit),id='material-slab';
 kit.manifest[id]={household:true,revision:1,maps:{base_color:`materials/${id}/maps/color.png`},
  params:{tint:'#123456',roughness:.7,metalness:0,tile_ft:[3,6],random_offset:true}};
 const p=structuredClone(plan);p.buildings[0].foundation.materials={slab:{id}};
 const first=await build(p,kit),mesh=slabs(first)[0];assert.equal(mesh.material.color.getHexString(),'123456');
 await mesh.material.userData.ready;
 assert.equal(mesh.material.userData.randomOffset,true);assert.deepEqual(mesh.material.map.repeat.toArray(),[1/3,1/6]);
 const noOffset=structuredClone(kit);noOffset.manifest[id].params.random_offset=false;
 const plain=slabs(await build(p,noOffset))[0],expected=plain.geometry.clone();
 offsetSurfaceUvs(expected,mesh.material,'b:foundation');
 assert.deepEqual([...mesh.geometry.attributes.uv.array],[...expected.attributes.uv.array]);
 const legacy=structuredClone(plan);legacy.materials={patio_concrete:{id}};
 assert.deepEqual(slabUvs(slabs(await build(legacy,kit))[0]),slabUvs(slabs(await build(legacy,noOffset))[0]),
  'missing slab slot keeps legacy foundation UVs even with a random-offset role');
 const repeat=slabs(await build(p,kit))[0];assert.deepEqual([...repeat.geometry.attributes.uv.array],[...mesh.geometry.attributes.uv.array]);
 const key=buildingKey(p,p.buildings[0],kit,'low');
 const revised=structuredClone(kit);revised.manifest[id].revision=2;revised.manifest[id].params.tint='#654321';
 assert.notEqual(buildingKey(p,p.buildings[0],revised,'low'),key,'a slab-only household material revision rebuilds its building');
 const updated=slabs(await build(p,revised,'low',first))[0];assert.equal(updated.material.color.getHexString(),'654321');
 p.buildings[0].foundation.materials.slab.color='#abcdef';
 assert.equal(slabs(await build(p,kit))[0].material.color.getHexString(),'abcdef');
});
await test('foundation_pick_and_tint_invalidate_bake_on_every_tier',async()=>{
 const options={room:{density:1,page:256,gutter:2}},plain=await build();
 const before=atlasJob(plain.root,plan,options).cacheKey;
 for(const value of [{id:ref.id},ref]){
  const p=structuredClone(plan);p.buildings[0].foundation.materials={slab:value};
  const low=await build(p),high=await build(p,input.kit,'high');
  assert.notEqual(atlasJob(low.root,p,options).cacheKey,before);
  assert.equal(buildAtlas(low.root,p,options).key,buildAtlas(high.root,p,options).key);
 }
});
await test('shelf_pick_clear_one_op_and_preserves_foundation_fields',async()=>{
 const {host,sent,errors}=shelf(),slot=host.querySelector('[data-material-slot="Slab"]');assert.ok(slot);
 assert.ok(textOf(slot).includes('Default: Concrete'));
 assert.equal(sent.length,0);
 await useMaterial(slot,ref.id);assert.equal(sent.length,1);
 assert.deepEqual(sent[0],{op:'set_foundation',building:'b',foundation:{...b.foundation,materials:{slab:{id:ref.id}}}});
 const tint=slot.querySelector('input[type="color"]');tint.value='#123456';await fire(tint,'change');
 assert.deepEqual(sent.at(-1),{op:'set_foundation',building:'b',foundation:{...b.foundation,materials:{slab:{id:ref.id,color:'#123456'}}}});
 await click(byText(slot,'Clear override'));
 assert.deepEqual(sent.at(-1),sent[0],'clearing tint restores the original selection payload');
 await click(byText(slot,'Clear'));assert.equal(sent.length,4);
 assert.deepEqual(sent.at(-1),{op:'set_foundation',building:'b',foundation:b.foundation});assert.deepEqual(errors,[]);
});
await test('numeric_commit_and_preview_keep_current_material',async()=>{
 const {host,sent,p,previews}=shelf();
 p.buildings[0].foundation.materials={slab:ref};
 const offset=host.querySelector('[aria-label="Offset (ft)"]');offset.value='3';await fire(offset,'input');
 await new Promise(resolve=>setTimeout(resolve,220));assert.equal(previews.length,1);
 assert.deepEqual(previews[0].buildings[0].foundation.materials,{slab:ref});
 await fire(offset,'change');assert.equal(sent.length,1);assert.deepEqual(sent[0].foundation.materials,{slab:ref});
 assert.equal(sent[0].foundation.offset_ft,3);
});
await test('readonly_slab_has_no_editing_control',async()=>{
 const {host,sent}=shelf({locked:true,foundation:{...b.foundation,materials:{slab:ref}}});
 const slot=host.querySelector('[data-material-slot="Slab"]');assert.ok(slot);
 assert.equal(slot.querySelectorAll('button,input').length,0);assert.equal(sent.length,0);
});
await test('real_building_card_supplies_kit_to_shared_slab_slot',async()=>{
 const p=structuredClone(plan);p.buildings[0].foundation.materials={slab:{id:'patio_concrete'}};
 let writable=true;
 const cards=createCards({getPlan:()=>p,getKit:()=>input.kit,getLabel:()=> 'House',library,canEdit:()=>writable,edit(){},op:async()=>{},ask(){}});
 cards.draw({pieceId:'b',buildingId:'b'});
 const slot=document.getElementById('piece-card').querySelector('[data-material-slot="Slab"]');assert.ok(slot);
 assert.equal(slot.querySelector('[data-slot-swatch]').style.backgroundColor,input.kit.materials.patio_concrete.color);
 writable=false;cards.draw();
 const readonly=document.getElementById('piece-card').querySelector('[data-material-slot="Slab"]');
 assert.equal(readonly.querySelectorAll('button,input').length,0,'history/read-only transition rebuilds the slot');
});
finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
