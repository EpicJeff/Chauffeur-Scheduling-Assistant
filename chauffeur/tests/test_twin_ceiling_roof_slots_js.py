"""Opt-in room ceilings through real geometry, view hiding and editor lines.

Roof overrides and their keys remain covered by test_twin_roof_material_js.py.
"""
import sys
from test_twin_untouched_house_js import COMMON, ROOT
from twin_editor_dom import run_node

DRIVER = COMMON + r"""
const {materialLines,surfaceOperation}=await import(file('static/twin/editor/library.js'));
const ceilingPlan=()=>{const p=fixture();p.buildings=[p.buildings[0]];const b=p.buildings[0];
 b.base=0;b.porches=[];b.stairs=[];b.rooms[0].polygon=square(1,1,18,22);return p;};
const ceilings=out=>meshes(out).filter(o=>o.material.name==='ceiling');
const near=(a,b)=>assert.ok(Math.abs(a-b)<2e-5,`${a} != ${b}`);
await test('no_ceiling_surface_when_unset',async()=>{const out=await build(ceilingPlan());assert.equal(ceilings(out).length,0);});
await test('room_ceiling_material_adds_one_surface_under_the_slab',async()=>{
 const p=ceilingPlan();p.buildings[0].rooms[0].ceiling_material={id:'choice'};
 const a=await build(ceilingPlan()),out=await build(p),cs=ceilings(out);assert.equal(cs.length,1);
 assert.equal(meshes(out).length,meshes(a).length+1);const c=cs[0];
 c.geometry.computeBoundingBox();const bb=c.geometry.boundingBox;
 near(bb.min.x,1);near(bb.max.x,19);near(bb.min.z,-23);near(bb.max.z,-1);
 near(bb.min.y,9-.8-.02);near(bb.max.y,9-.8-.02);
 assert.ok(Array.from(c.geometry.attributes.normal.array).filter((_,i)=>i%3===1).every(y=>y<-.99));
 assert.equal(c.userData.pieceId,'r1');assert.equal(c.userData.kind,'room');assert.equal(c.userData.part,'ceiling');
 assert.equal(c.material.userData.materialId,'choice');
 assert.ok(out.groups.levels['a:L2'].children.includes(c.parent));
});
await test('ceiling_hides_with_its_underside',async()=>{
 const {mountTwin}=await import(file('static/twin/twin_view.js'));
 for(const room of ['r1','r2']){
  const p=ceilingPlan();p.buildings[0].rooms.find(r=>r.id===room).ceiling_material={id:'choice'};
  const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
  const view=await mountTwin(host,{plan:p,kit:kit(),tier:'low',bake:false});
  try{const cs=[];view.scene.traverse(o=>{if(o.isMesh&&o.material.name==='ceiling')cs.push(o);});assert.equal(cs.length,1);
   const shown=o=>{for(let p=o;p;p=p.parent)if(!p.visible)return false;return true;};
   view.setView('ext');assert.ok(shown(cs[0]));view.setView('a:L1');assert.ok(!shown(cs[0]));
  }finally{view.dispose();}
 }
});
await test('house_ceiling_default_covers_every_room',async()=>{
 const p=ceilingPlan(),b=p.buildings[0];b.materials.ceiling={id:'blend'};b.rooms[0].ceiling_material={id:'choice'};
 const out=await build(p),cs=ceilings(out);assert.equal(cs.length,2);
 assert.equal(cs.find(o=>o.userData.pieceId==='r1').material.userData.materialId,'choice');
 assert.equal(cs.find(o=>o.userData.pieceId==='r2').material.userData.materialId,'blend');
 const roof=cs.find(o=>o.userData.pieceId==='r2');assert.ok(out.groups.roof.children.includes(roof.parent));
 const pos=roof.geometry.attributes.position;
 for(let i=0;i<pos.count;i++)near(pos.getY(i),17+Math.min(pos.getX(i),20-pos.getX(i))*.5-.25-.02);
});
await test('ceiling_material_and_revision_change_the_key_and_clear_back',()=>{
 const p=ceilingPlan(),b=p.buildings[0],k=kit(),key=()=>JSON.stringify(G.buildingKeyParts(p,b,k,'low'));
 const before=key();b.rooms[0].ceiling_material={id:'choice'};const after=key();assert.notEqual(after,before);
 k.manifest.choice.revision++;assert.notEqual(key(),after);delete b.rooms[0].ceiling_material;assert.equal(key(),before);
 b.materials.ceiling={id:'blend'};assert.notEqual(key(),before);delete b.materials.ceiling;assert.equal(key(),before);
});
await test('kit_alias_ceiling_keeps_its_receiving_role',async()=>{
 const p=ceilingPlan();p.buildings[0].rooms[0].ceiling_material={id:'trim',color:'#123456'};
 const out=await build(p);assert.equal(ceilings(out).length,1);assert.ok(meshes(out).some(o=>o.material.name==='trim'));
});
await test('partial_upper_storey_ceiling_patches_share_each_support_visibility',async()=>{
 const p=ceilingPlan(),b=p.buildings[0];b.rooms[0].polygon=square(1,1,38,22);b.rooms[0].ceiling_material={id:'choice'};
 const out=await build(p),cs=ceilings(out);assert.equal(cs.length,2);
 const slab=cs.find(o=>out.groups.levels['a:L2'].children.includes(o.parent));
 const roof=cs.find(o=>out.groups.roof.children.includes(o.parent));assert.ok(slab&&roof);
 slab.geometry.computeBoundingBox();roof.geometry.computeBoundingBox();near(slab.geometry.boundingBox.max.x,20);near(roof.geometry.boundingBox.min.x,20);
});
await test('ceiling_line_uses_role_ceiling',()=>{
 const p=ceilingPlan(),b=p.buildings[0],piece=b.rooms[0];
 const line=materialLines({kind:'room',piece,building:b},p,kit()).find(l=>l.label==='Ceiling');
 assert.ok(line);assert.equal(line.text,'House default: Ceiling');assert.equal(line.surface.role,'ceiling');
 assert.deepEqual(line.target,{room:piece.id,surface:'ceiling'});
 assert.equal(surfaceOperation(line.surface,'building',{id:'choice'}).target.role,'ceiling');
 const porch={...piece,kind:'porch'};
 const old=materialLines({kind:'room',piece:porch,building:b},p,kit()).find(l=>l.label==='Ceiling');
 assert.equal(old.surface.role,'porch_ceiling','existing porch ceiling scope remains usable');
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output)
    sys.exit(code or 0)
