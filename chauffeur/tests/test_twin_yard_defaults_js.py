"""Site defaults through the real yard builder, materials and reuse keys."""
import sys
from test_twin_untouched_house_js import COMMON, ROOT
from twin_editor_dom import run_node

DRIVER = COMMON + r"""
const Y=await import(file('static/twin/twin_yard.js'));
const yard=async p=>(await Y.buildYard(p,kit(),'low')).group;
const all=g=>{const rows=[];g.traverse(o=>{if(o.isMesh)rows.push(o);});return rows;};
await test('water_default_reaches_pool_and_spa',async()=>{
 const p=fixture();p.materials.water={id:'blend'};
 // Per-item water is slice C: even a stored value must not replace the site default.
 p.site.pool.materials={water:{id:'choice'}};p.site.pool.features[0].materials={water:{id:'choice'}};
 const g=await yard(p),water=all(g).filter(o=>o.material.name==='water');
 assert.ok(water.length);assert.ok(water.every(o=>o.material.userData.materialId==='blend'));
 const ys=water.flatMap(o=>Array.from(o.geometry.attributes.position.array).filter((_,i)=>i%3===1));
 assert.ok(ys.some(y=>Math.abs(y+.25)<1e-5),'pool');
 assert.ok(ys.some(y=>y>1),'raised spa');
 assert.equal(new Set(water.map(o=>o.material)).size,1);
});
await test('builtin_water_slot_equals_todays_water',async()=>{
 const p=fixture(),a=all(await yard(p)).find(o=>o.material.name==='water').material;
 p.materials.water={id:'water'};
 const b=all(await yard(p)).find(o=>o.material.name==='water').material;
 for(const key of ['name','transparent','opacity','roughness','metalness','depthWrite','side','alphaTest','vertexColors'])assert.equal(b[key],a[key],key);
 assert.equal(b.color.getHex(),a.color.getHex());
});
await test('water_default_changes_the_yard_key',()=>{
 const p=fixture(),k=kit(),before=Y.yardMaterialKey(p,k,'low');p.materials.water={id:'blend'};
 const after=Y.yardMaterialKey(p,k,'low');assert.notEqual(after,before);
 assert.equal(after,Y.yardMaterialKey(structuredClone(p),k,'low'));
 k.manifest.blend.revision++;assert.notEqual(after,Y.yardMaterialKey(p,k,'low'));
 delete p.materials.water;assert.equal(before,Y.yardMaterialKey(p,k,'low'));
});
await test('kit_alias_water_retains_the_water_role_without_renaming_paving',async()=>{
 for(const slot of [{id:'paving'},{id:'paving',color:'#123456'}]){
  const p=fixture();p.materials.water=slot;const g=await yard(p),ms=all(g);
  assert.ok(ms.some(o=>o.material.name==='water'));assert.ok(ms.some(o=>o.material.name==='paving'));
 }
});
await test('lawn_default_still_works_on_flat_and_graded_lots',async()=>{
 for(const graded of [false,true]){
  const p=fixture();p.materials.lawn={id:'choice'};
  if(graded)p.site.terraces=[{id:'pad',polygon:square(0,0,20),height:2,blend:3,edges:[]}];
  const grass=all(await yard(p)).filter(o=>o.material.userData.materialId==='choice');
  assert.ok(grass.some(o=>!o.material.vertexColors),'flat continuation');
  assert.ok(grass.some(o=>o.material.vertexColors&&o.material.side===THREE.DoubleSide),'terrain lawn');
 }
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)
