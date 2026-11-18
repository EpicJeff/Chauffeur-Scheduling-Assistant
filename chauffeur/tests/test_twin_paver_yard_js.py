"""Run the paver yard surface, ownership and bake receiver under Node."""
import json
import sys
from test_twin_ground_js import PREFIX, ROOT
from twin_editor_dom import run_node

DRIVER = PREFIX + r"""
const THREE=await import(three);
const {buildYard,yardPartKeys}=await import(file('static/twin/twin_yard.js'));
const {paverLayout,paverEstimate,PAVER_DEFAULTS}=await import(file('static/twin/paver_layout.js'));
const {paverGeometry}=await import(file('static/twin/paver_geometry.js'));
const {pathPresets,pathSurfacePolygons}=await import(file('static/twin/path_shapes.js'));
const {terrainSlabGeometry}=await import(file('static/twin/twin_terrain_mesh.js'));
const {atlasMesh}=await import(file('static/twin/bake/atlas.js'));
const {groundAt}=await import(file('static/twin/twin_ground.js'));
const path={id:'walk',kind:'path',points:[[2,5],[14,5]],width:5,material:'paving',pavers:{...PAVER_DEFAULTS}};
const plan=h=>({buildings:[],site:{hardscape:[h]}});
const meshes=async(h,p=plan(h))=>(await buildYard(p,kit,'low')).group.children.filter(o=>o.userData.yardPart==='hardscape');
const triangles=g=>(g.index?.count||g.attributes.position.count)/3;
assert.deepEqual(pathPresets.paver.pavers,PAVER_DEFAULTS);
const blocks=await meshes(path),layout=paverLayout(path);
assert.equal(paverGeometry(plan(path),path,layout).userData.paverPath,true);
assert.equal(blocks.length,1,'one surface and no continuous slab');
assert.equal(triangles(blocks[0].geometry),layout.pavers.length*20,'bevelled rectangular prism: 2 top, 2 bottom, 8 bevel, 8 side triangles');
assert.ok(blocks[0].userData.snapRanges.every(r=>r.kind==='hardscape'&&r.pieceId==='walk'));
assert.ok(atlasMesh(blocks[0]),'merged pavers receive bake exactly like the slab');
assert.ok(blocks[0].geometry.attributes.normal&&blocks[0].geometry.attributes.uv);
for(const joint of ['grass','none','sand','gravel']){
 const h={...path,pavers:{...path.pavers,joint}},m=await meshes(h);
 assert.equal(m.length,['sand','gravel'].includes(joint)?2:1,joint);
 if(joint==='sand')assert.ok(m.some(o=>o.material.color.getHexString()==='cdb994'&&o.material.roughness===.95));
 if(joint==='gravel')assert.ok(m.some(o=>o.material.name==='base'));
}
const slotted=await meshes({...path,pavers:{...path.pavers,joint:'gravel'},materials:{joint:{id:'patio_concrete',color:'#cc1122'}}});
assert.ok(slotted.some(o=>o.material.color.getHexString()==='cc1122'),'joint slot resolved');
assert.ok((await meshes({...path,edging:'curb'})).length>1,'curbs retained');
for(const elevation of [0,1]){
 const h={...path,elevation},p=plan(h);p.site.terraces=[{polygon:[[0,0],[20,0],[20,10],[0,10]],height:-2,blend:0}];
 const m=(await meshes(h,p))[0],a=m.geometry.attributes.position,ys=Array.from({length:a.count},(_,i)=>a.getY(i));
 assert.ok(Math.abs(Math.max(...ys)-(groundAt(p,...layout.pavers[0].centre)+elevation+1/12))<1e-6);
 assert.ok(Math.abs(Math.min(...ys)-(-2+elevation-2/12))<1e-6);
}
const old={...path};delete old.pavers;
const slab=await meshes(old),expected=pathSurfacePolygons(old).map(p=>terrainSlabGeometry(plan(old),p,'low',0,.3));
assert.equal(slab.length,1);assert.equal(triangles(slab[0].geometry),expected.reduce((n,g)=>n+triangles(g),0));assert.ok(atlasMesh(slab[0]));
const refused={...path,points:[[0,0],[13.75,0],[13.75,13.75]],smooth:true,width:5,pavers:{...path.pavers,length_in:2,width_in:2,gap_in:0}};
assert.ok(27.5*5*36<=5000&&paverEstimate(refused)>5000,'raw server estimate passes; smoothed client estimate refuses');
let warnings=0;const warn=console.warn;console.warn=()=>warnings++;
try{const m=await meshes(refused);assert.equal(m.length,1);assert.ok(triangles(m[0].geometry)>0);await meshes(structuredClone(refused));assert.equal(warnings,1);}finally{console.warn=warn;}
assert.notEqual(yardPartKeys(plan(path),kit,'low').hardscape,yardPartKeys(plan(old),kit,'low').hardscape,'paver edits invalidate hardscape');
console.log('Paver yard: geometry, joints, slots, curb, grade, legacy slab, cap fallback and atlas passed');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}, timeout=180)
    print(output)
    sys.exit(code or 0)
