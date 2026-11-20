"""Real household: finish edits keep atlas addresses and dirty physical reach locally."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_twin_surface_slots_household_js as H
from services import twin_model_bridge as bridge
from twin_editor_dom import run_node

DRIVER = H.DRIVER[:H.DRIVER.index('for (const tier')] + r"""
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const {bakeLayout}=await import(file('static/twin/bake/baker.js'));
const {atlasJob}=await import(file('static/twin/bake/atlas_transport.js'));
const {materialParts}=await import(file('static/twin/bake/bindings.js'));
const options={room:{density:1,page:1024,gutter:2}};
const build=async plan=>{const h=buildTwin(plan,input.kit,'low',{viewing:true});await h.ready;
 const y=await buildYard(plan,input.kit,'low',{viewing:true});h.root.add(y.group);h.root.updateMatrixWorld(true);
 return {root:h.root,roofs:h.roofSurfaces,atlas:buildAtlas(h.root,plan,options)};};
const base=await build(input.plan);
const layout=a=>({pages:a.room.pages,rooms:a.room.rooms,charts:a.room.charts.map(c=>[c.id,c.key,c.page,c.rect,c.room,c.density])});
const lights=input.plan.buildings.flatMap(b=>b.rooms.filter(r=>r.polygon?.length).map(r=>({device:b.id+':'+r.id,
 building:b.id,level:r.level,room:r.id,at:[r.polygon.reduce((s,p)=>s+p[0],0)/r.polygon.length,
 r.polygon.reduce((s,p)=>s+p[1],0)/r.polygon.length,(b.levels.find(l=>l.id===r.level)?.elevation||0)+5]})));
const packed=bakeLayout(base.atlas,options,lights);
const finishes=chart=>JSON.stringify([...new Set(materialParts(chart).map(({mesh})=>JSON.stringify([
 mesh.material.userData.materialId||mesh.material.userData.bakeMaterialId||null,
 mesh.material.userData.materialRevision??null,mesh.material.color?.toArray()])))].sort());
for(const [name,edit] of [
 ['wall',p=>{const w=p.buildings[0].walls.find(w=>w.exterior);w.faces={...w.faces,left:{color:'#224466'}};}],
 ['roof-plane',p=>{const b=p.buildings[0],roof=base.roofs.get(b.id),t=Array.from(roof.edge).findIndex(e=>e>=0);
   assert.ok(t>=0);b.roof.sections[roof.section[t]].plane_materials={[roof.edge[t]]:{id:'wood_floor',color:'#224466'}};}],
 ['house-role',p=>{p.materials={...p.materials,interior_wall:{color:'#224466'}};}],
 ['level-role',p=>{p.buildings[0].levels[0].materials={interior_wall:{color:'#224466'}};}],
 ['room-wall',p=>{p.buildings[0].rooms[0].wall_material={color:'#224466'};}],
 ['uv',p=>{const w=p.buildings[0].walls.find(w=>w.exterior);w.faces={...w.faces,left:{uv:{u:.25,v:.5,rot:90}}};}],
 ['roof-uv',p=>{const b=p.buildings[0],roof=base.roofs.get(b.id),t=Array.from(roof.edge).findIndex(e=>e>=0);
   b.roof.sections[roof.section[t]].plane_materials={[roof.edge[t]]:{uv:{u:.25,v:.5,rot:90}}};}]
]){
 const p=structuredClone(input.plan);edit(p);
 assert.equal(authoredGeometry(p),authoredGeometry(input.plan),name+' authored key');
 const after=await build(p);
 assert.equal(after.atlas.key,base.atlas.key,name+' atlas key');
 assert.deepEqual(layout(after.atlas),layout(base.atlas),name+' stable chart ownership and pages');
 const next=bakeLayout(after.atlas,options,lights,packed.ownership,packed.entries);
 const stale=lights.filter(l=>packed.entries[l.device]?.key!==next.entries[l.device]?.key).map(l=>l.device);
 const changedCharts=new Set(after.atlas.room.charts.filter((c,i)=>finishes(c)!==finishes(base.atlas.room.charts[i])).map(c=>c.id));
 const expected=packed.lights.filter(l=>l.receivingCharts.some(id=>changedCharts.has(id))).map(l=>l.device);
 assert.deepEqual(stale.slice().sort(),expected.sort(),name+' dirties exactly lights reaching changed chart finishes');
 assert.ok(name.endsWith('uv')?stale.length===0:stale.length>0,name+' expected dirty reach');
 assert.ok(stale.length<lights.length,name+' preserves remote lights');
 const pages=new Set(stale.flatMap(id=>next.entries[id]?.pages||[]));
 console.log(JSON.stringify({name,charts:after.atlas.room.charts.length,changedCharts:changedCharts.size,pages:after.atlas.room.pages,rebakeLights:stale.length,dirtyPages:pages.size,totalLights:lights.length}));
}
const moved=structuredClone(input.plan);moved.buildings[0].walls[0].to[0]+=.5;
assert.notEqual(authoredGeometry(moved),authoredGeometry(input.plan),'wall geometry invalidates');
console.log('PASS household local surface reach');
"""

if __name__ == '__main__':
    fixture = json.loads((H.ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = bridge.flatten(bridge.assemble(fixture)[0])
    kit = json.loads((H.ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': H.ROOT.as_posix(), 'plan': plan, 'kit': kit}, timeout=600)
    print(output)
    assert code == 0, output
