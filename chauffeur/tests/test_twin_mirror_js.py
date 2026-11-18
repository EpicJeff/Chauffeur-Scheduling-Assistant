"""Winding through real builders at every tier, with CPU model/tree fixtures."""
import json
from pathlib import Path
import sys
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PREFIX = PREFIX.replace("if (spec === 'three')", """if ((spec.endsWith('/twin_library.js') || spec === './twin_library.js') && !ctx.parentURL?.startsWith('data:')) return {url:data(`
  export * from '${file('static/twin/twin_library.js')}';
  export async function loadModel(id,kit,onLate){const source=globalThis.__mirrorSource.clone(true);
    if(globalThis.__mirrorLate){globalThis.__mirrorDeliveries.push(()=>onLate?.(source));return null;}return source;}
  `),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = r"""
const THREE=await import('three');
const objects=await import(file('static/twin/objects.js'));
const {buildTwin,mergeStatic}=await import(file('static/twin/twin_generator.js'));
const {buildYard}=await import(file('static/twin/twin_yard.js'));
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
window.twinObjectSchema=input.schema;
globalThis.__mirrorSource=new THREE.Group();
const sourceMesh=new THREE.Mesh(new THREE.BoxGeometry(.6,1,.3),new THREE.MeshStandardMaterial());sourceMesh.position.set(.2,.5,.1);__mirrorSource.add(sourceMesh);
const assertWinding=(g,label)=>{
 const p=g.attributes.position,n=g.attributes.normal,idx=g.index;
 assert.ok(n,label+' normals');let count=0;
 for(let i=0;i<(idx?.count||p.count);i+=3){const ids=[0,1,2].map(k=>idx?idx.getX(i+k):i+k);
  const v=ids.map(j=>new THREE.Vector3().fromBufferAttribute(p,j));
  const face=v[1].sub(v[0]).cross(v[2].sub(v[0]));if(face.lengthSq()<1e-16)continue;
  const normal=ids.reduce((sum,j)=>sum.add(new THREE.Vector3().fromBufferAttribute(n,j)),new THREE.Vector3());
  assert.ok(face.dot(normal)>0,label+' triangle '+i/3+' faces its normals');count++;
 } assert.ok(count,label+' has triangles');return count;
};
for(const mirrors of [{mirror_x:true},{mirror_y:true},{mirror_x:true,mirror_y:true}]){
 const model=objects.applyObject(__mirrorSource.clone(true),{...mirrors,scale:2,scale_axes:[2,3,4]},{units:1});
 assert.equal(model.scale.x,mirrors.mirror_x?-4:4);assert.equal(model.scale.y,6);assert.equal(model.scale.z,mirrors.mirror_y?-8:8);
 const bounds=new THREE.Box3().setFromObject(model);assert.ok(!bounds.isEmpty());
 model.updateMatrixWorld(true);const hits=new THREE.Raycaster(new THREE.Vector3(bounds.getCenter(new THREE.Vector3()).x,20,bounds.getCenter(new THREE.Vector3()).z),new THREE.Vector3(0,-1,0)).intersectObject(model,true);
 assert.ok(hits.length,'mirrored object still picks');
}
assert.equal(typeof objects.bakeMatrix,'function');
for(const indexed of [true,false])for(const negative of [true,false]){
 let g=new THREE.BoxGeometry(1,2,3);if(!indexed)g=g.toNonIndexed();const order=g.index&&Array.from(g.index.array);
 const matrix=new THREE.Matrix4().makeRotationY(.7).multiply(new THREE.Matrix4().makeScale(negative?-2:2,3,4));
 assert.equal(objects.bakeMatrix(g,matrix),g);assertWinding(g,'shared '+indexed+' '+negative);
 if(!negative&&indexed)assert.deepEqual(Array.from(g.index.array),order);
}
const merged=new THREE.Group(),child=__mirrorSource.clone(true);child.scale.x=-1;merged.add(child);mergeStatic(merged);
merged.traverse(o=>{if(o.isMesh)assertWinding(o.geometry,'mergeStatic');});
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const atlas=buildAtlas(merged,{buildings:[],site:{}});assert.ok(atlas.room.charts.length,'atlas charts the corrected baked mesh');
merged.traverse(o=>{if(o.isMesh)assertWinding(o.geometry,'atlas receiver');});

const plan=structuredClone(input.plan),b=plan.buildings[0],level=b.levels[0],room=b.rooms[0],wall=b.walls.find(w=>Math.hypot(w.to[0]-w.from[0],w.to[1]-w.from[1])>9);
const host={floor:room.id,u:.5,v:.5};
b.items=[{id:'mirror-item',asset:'model',host,mirror_x:true}];
b.fixtures=[{id:'mirror-rect',kind:'counter',level:level.id,rect:[2,2,4,4],height:3,mirror_y:true}];
b.lights=[{id:'mirror-light',kind:'recessed',level:level.id,at:[4,4],mirror_x:true}];
b.anchors=[{id:'mirror-anchor',kind:'switch',host,mirror_y:true}];
b.openings=[{id:'right-door',wall:wall.id,at:2,width:2,sill:0,head:7,kind:'door',model:'model',hinge:'right'},
 {id:'out-door',wall:wall.id,at:6,width:2,sill:0,head:7,kind:'door',model:'model',swing:'out'}];
plan.site={furniture:[{id:'yard-chair',asset:'model',at:[50,50],mirror_y:true}],planting:[{id:'plant-model',asset:'import-plant',at:[55,55],mirror_x:true},
 {id:'preset-tree',preset:'oak',height:10,at:[60,60],mirror_x:true}]};
for(const tier of ['low','medium','high'])for(const viewing of [false,true])for(const late of [false,true]){
 globalThis.__mirrorLate=late;globalThis.__mirrorDeliveries=[];
 const built=buildTwin(plan,input.kit,tier,{viewing,showAnchors:true});await built.ready;
 const yard=(await buildYard(plan,input.kit,tier,{viewing})).group;
 for(const deliver of __mirrorDeliveries)deliver();
 const targets=['mirror-item','mirror-rect','mirror-light','mirror-anchor','right-door','out-door'],seen=new Set();let triangles=0;
 built.root.traverse(o=>{if(!o.isMesh||o.layers.isEnabled(31))return;
   const ids=[o.userData.pieceId,...(o.userData.snapRanges||[]).map(r=>r.pieceId)].filter(id=>targets.includes(id));
   if(o.userData.merged||ids.length){ids.forEach(id=>seen.add(id));triangles+=assertWinding(o.geometry,tier+' '+viewing+' '+late+' '+ids.join(','));}
 });
 for(const id of targets)assert.ok(seen.has(id),'built target '+id);
 let yardMeshes=0;yard.traverse(o=>{if(o.isMesh){yardMeshes++;assertWinding(o.geometry,'yard '+tier+' '+viewing+' '+late);}});assert.ok(yardMeshes>=1);
 console.log('ok '+tier+' viewing='+viewing+' late='+late+' winding '+triangles+' house triangles, '+yardMeshes+' yard meshes');
}
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
for(const target of [{building:b.id,id:'mirror-item'},{list:'furniture',index:0}]){
 const mirrored=applyLocal(plan,{op:'set_object',...target,properties:{mirror_x:true,mirror_y:true}}).plan;
 const read=p=>target.building?p.buildings[0].items[0]:p.site.furniture[0];assert.equal(read(mirrored).mirror_x,true);
 const cleared=applyLocal(mirrored,{op:'set_object',...target,properties:{mirror_x:false}}).plan;
 assert.ok(!Object.hasOwn(read(cleared),'mirror_x'));assert.equal(read(cleared).mirror_y,true);
}
const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
for(const record of [{kind:'item',building:b,piece:b.items[0]},{kind:'furniture',index:0,piece:plan.site.furniture[0]}]){
 const host=document.createElement('div');document.body.append(host);const ops=[];let pending=Promise.resolve();
 drawObjectShelf(host,record,{canEdit:()=>true,queue:work=>pending=pending.then(work),op:async op=>ops.push(op),report:e=>{throw e;}});
 for(const [key,label]of [['mirror_x','Mirror left-right'],['mirror_y','Mirror front-back']]){
   const input=host.querySelector('[aria-label="'+label+'"]');assert.ok(input);input.checked=true;fire(input,'change');await pending;
   assert.deepEqual(ops.at(-1).properties,{[key]:true});
 } assert.equal(ops.length,2);host.remove();
}
console.log('PASS mirror scales, ray picking, winding, all builders/tiers/viewing/late, local replay and shelf');
"""


def run():
    from services import twin_plan, twin_model_bridge
    fixture = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text())
    plan = twin_model_bridge.flatten(twin_model_bridge.assemble(twin_plan.normalize(fixture)[0])[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text()); kit['manifest'] = {}
    driver = DRIVER
    if '--doors-baseline' in sys.argv:
        driver = DRIVER.split('for(const mirrors')[0] + 'const plan=' + DRIVER.split('const plan=', 1)[1].split('for(const tier')[0] + r"""
b.items=[];b.fixtures=[];b.lights=[];b.anchors=[];
const built=buildTwin(plan,input.kit,'low');await built.ready;
let checked=0;built.root.traverse(o=>{if(o.isMesh&&!o.layers.isEnabled(31)&&
  [o.userData.pieceId,...(o.userData.snapRanges||[]).map(r=>r.pieceId)].some(id=>['right-door','out-door'].includes(id))){
  checked++;assertWinding(o.geometry,'existing door');}});assert.ok(checked);console.log('PASS existing door winding');
"""
    code, output = run_node(PREFIX + driver, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit,
        'schema': json.loads((ROOT / 'static/twin/object_schema.json').read_text())})
    print(output, end='')
    assert code == 0, output


if __name__ == '__main__':
    run()
