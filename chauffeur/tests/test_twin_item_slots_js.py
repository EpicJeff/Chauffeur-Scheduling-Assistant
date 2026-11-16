"""Item material resolution, batching, part picking and bake/reuse identities."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT, run_node

DRIVER = COMMON + r"""
const Y=await import(file('static/twin/twin_yard.js'));
const parts=(out,id)=>out.pickObjects.get('a:'+id)?.userData.partObjects?.map(p=>p.object)||[];
const own=(out,id,part)=>parts(out,id).filter(o=>o.userData.part===part);
await test('item_slot_beats_house_default_beats_fallback',async()=>{
 for(const [collection,id,part,name] of [['openings','window','pane','glass'],['porches','porch','screen','screen'],
  ['stairs','stairs','stair_rail','porch_ceiling'],['fixtures','vanity','counter','counter']]){
  const p=fixture(),b=p.buildings[0],item=b[collection].find(o=>o.id===id);
  b.materials[part]={id:'blend'};item.materials={[part]:{id:'choice'}};
  const a=await build(p);assert.ok(own(a,id,part).length,id);assert.ok(own(a,id,part).every(o=>o.material.userData.materialId==='choice'));
  delete item.materials;const c=await build(p);assert.ok(own(c,id,part).every(o=>o.material.userData.materialId==='blend'));
  delete b.materials[part];const d=await build(p);assert.ok(own(d,id,part).every(o=>!o.material.userData.materialId&&o.material.name===name));
 }
 const p=fixture(),f=p.buildings[0].fixtures[0];f.materials={cabinet:{id:'choice'},counter:{id:'choice'}};
 const out=await build(p);for(const part of ['cabinet','counter'])assert.ok(own(out,'kitchen',part).every(o=>o.material.userData.materialId==='choice'),'slot wins over existing colour');
});
await test('only_the_named_item_changes',async()=>{
 const p=fixture();p.buildings[0].openings[0].materials={pane:{id:'choice'}};const out=await build(p);
 assert.ok(own(out,'window','pane').every(o=>o.material.userData.materialId==='choice'));
 const other=own(out,'slider','pane')[0].material;assert.equal(other,own(out,'bifold','pane')[0].material);
 assert.equal(other.userData.materialId,undefined);assert.equal(other.name,'glass');
 assert.ok(own(out,'window','window_frame').every(o=>!o.material.userData.materialId));
});
await test('two_items_with_the_same_slot_share_one_material',async()=>{
 const p=fixture();for(const o of p.buildings[0].openings.slice(0,2))o.materials={pane:{id:'choice'}};
 const out=await build(p);assert.equal(own(out,'window','pane')[0].material,own(out,'slider','pane')[0].material);
});
await test('spa_water_follows_pool_then_house',async()=>{
 const p=fixture(),pool=p.site.pool,spa=pool.features[0];p.materials.water={id:'blend'};pool.materials={water:{id:'choice'}};
 spa.materials={water:{id:'glass',color:'#112233'}};
 const water=out=>{const found=[];out.group.traverse(o=>{if(o.isMesh&&o.material.name==='water')found.push(o.material);});return found;};
 let out=await Y.buildYard(p,kit(),'low');assert.ok(water(out).some(m=>m.color.getHexString()==='112233'));
 delete spa.materials;out=await Y.buildYard(p,kit(),'low');assert.ok(water(out).every(m=>m.userData.materialId==='choice'));
 delete pool.materials;out=await Y.buildYard(p,kit(),'low');assert.ok(water(out).every(m=>m.userData.materialId==='blend'));
 const before=Y.yardMaterialKey(p,kit(),'low');spa.materials={water:{id:'choice'}};assert.notEqual(Y.yardMaterialKey(p,kit(),'low'),before);
 const revised=kit();const key=Y.yardMaterialKey(p,revised,'low');revised.manifest.choice.revision++;assert.notEqual(Y.yardMaterialKey(p,revised,'low'),key);
});
await test('item_slot_changes_reuse_and_atlas_keys',async()=>{
 const p=fixture(),b=p.buildings[0],k=kit(),base=await build(p,k),key=G.buildingKeyParts(p,b,k,'low'),atlas=A.buildAtlas(base.root,p,layout).key;
 b.openings[0].materials={pane:{id:'choice'}};const out=await build(p,k);
 assert.notDeepEqual(G.buildingKeyParts(p,b,k,'low'),key);assert.notEqual(A.buildAtlas(out.root,p,layout).key,atlas);
 const changed=G.buildingKeyParts(p,b,k,'low');k.manifest.choice.revision++;assert.notDeepEqual(G.buildingKeyParts(p,b,k,'low'),changed);
 b.openings[0].materials={pane:{id:'glass'}};const glass=await build(p,k);
 assert.notDeepEqual(G.buildingKeyParts(p,b,k,'low'),key);
 const m=own(glass,'window','pane')[0].material,plain=own(base,'window','pane')[0].material;
 for(const prop of ['name','transparent','opacity','depthWrite','roughness'])assert.equal(m[prop],plain[prop],prop);
 assert.equal(m.color.getHexString(),plain.color.getHexString());
});
await test('part_tags_are_present',async()=>{
 const out=await build(fixture());
 for(const [id,expected] of [['window',['pane','window_frame','casing']],['door',['door','pane','casing','window_frame']],
  ['garage',['garage_door','window_frame','casing']],['porch',['column','screen']],['stairs',['stair_tread','stair_rail']],
  ['kitchen',['cabinet','counter']],['shower',['shower_tile','shower_glass']]])
  assert.deepEqual([...new Set(parts(out,id).map(o=>o.userData.part))].sort(),expected.sort(),id);
});
await test('mesh_count_unchanged_by_tags',async()=>{
 const p=fixture(),out=await build(p);for(const proxy of out.pickObjects.values())for(const entry of proxy.userData.partObjects||[])
  assert.ok(entry.object.isMesh&&entry.group.isObject3D);
 // The baseline graph/UV/material/count equality is also run in the pinned untouched-house file.
 assert.ok(meshes(out).length>0);
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'editable': True}, timeout=180)
    print(output)
    sys.exit(code or 0)
