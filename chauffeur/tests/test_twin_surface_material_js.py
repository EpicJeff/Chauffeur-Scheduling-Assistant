"""Slice 7 renderer contract, exercised with real Three geometry under Node."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_surface_material_')
from services import twin_model_bridge as bridge, twin_model_roofs
from test_twin_tree_once_js import PREFIX
from twin_editor_dom import run_node

DRIVER = PREFIX + r"""
const {resolveSurfaceMaterial} = await import(file('static/twin/surface_material.js'));
const lib = await import(file('static/twin/twin_library.js'));
const THREE = await import('three');
const kit={materials:{siding:{asset:'kit-siding',color:'#eeeeee'}}};
const plan={materials:{siding:{id:'house'}}};
const building={materials:{siding:{id:'building'}}};
const level={materials:{siding:{id:'level'}}};
const room={wall_material:{id:'room'}};
const surface={role:'siding',kit,building,level,room,roomRole:'wall',ref:{id:'surface'}};
for (const kind of ['surface','room','level','building','house','kit']) {
 const got=resolveSurfaceMaterial(plan,surface);
 assert.equal(got.source.kind,kind);assert.equal(got.source.id,kind==='kit'?'kit-siding':kind);
 if(kind==='surface')delete surface.ref;
 if(kind==='room')delete surface.room;
 if(kind==='level')delete surface.level;
 if(kind==='building')delete surface.building;
 if(kind==='house')delete plan.materials.siding;
}
const inherited=resolveSurfaceMaterial({materials:{siding:{id:'wood',color:'#123456',uv:{u:.1,v:.2,rot:0}}}},
 {role:'siding',kit,ref:{color:'#abcdef',uv:{u:0,v:0,rot:0}}});
assert.deepEqual(inherited,{ref:{id:'wood',color:'#abcdef',uv:{u:0,v:0,rot:0}},source:{kind:'house',id:'wood'}});
const followed=resolveSurfaceMaterial({materials:{trim:{id:'wood'}}},{role:'fascia',kit,
 fallback:resolveSurfaceMaterial({materials:{trim:{id:'wood'}}},{role:'trim',kit}),ref:{color:'#aabbcc'}});
assert.deepEqual(followed,{ref:{id:'wood',color:'#aabbcc'},source:{kind:'house',id:'wood'}});
const g=new THREE.PlaneGeometry(8,4),other=g.clone();
const m=new THREE.MeshStandardMaterial();m.userData.tileFt=[4,2];m.userData.randomOffset=true;
const before=Array.from(g.attributes.uv.array),program=m.customProgramCacheKey(),materialJSON=JSON.stringify(m.toJSON()),version=m.version;
lib.offsetSurfaceUvs(g,m,'surface',{u:.25,v:.5,rot:90});
assert.deepEqual(Array.from(other.attributes.uv.array),before);
for(let i=0;i<g.attributes.uv.count;i++){
 const u=before[2*i],v=before[2*i+1];
 // UVs are in feet: rotate in repeat space, about this surface's centre.
 assert.ok(Math.abs(g.attributes.uv.getX(i)-( .5-(v-.5)*2+1))<1e-6);
 assert.ok(Math.abs(g.attributes.uv.getY(i)-( .5+(u-.5)/2+1))<1e-6);
}
const zero=other.clone();lib.offsetSurfaceUvs(zero,m,'surface',{u:0,v:0,rot:0});
assert.deepEqual(Array.from(zero.attributes.uv.array),before);
assert.equal(m.customProgramCacheKey(),program);
assert.equal(JSON.stringify(m.toJSON()),materialJSON);assert.equal(m.version,version,'UV edit changes no material/program state');
console.log('ok resolver inheritance, partial refs, explicit UV and stable program key');
const {buildTwin,buildingKey}=await import(file('static/twin/twin_generator.js'));
const {buildYard,yardPartKeys}=await import(file('static/twin/twin_yard.js'));
const {roofMesh,planes,rectangleEdgeIndices}=await import(file('static/twin/twin_roof.js'));
for(const x of input.mappings)assert.deepEqual(rectangleEdgeIndices(x.area,x.rect),x.expected);
assert.ok(input.mappings.length>5,'every household roof has a Python mapping');
console.log('ok JS/Python area-edge mappings on '+input.mappings.length+' household sections');
const calls=root=>{let n=0;root.traverseVisible(o=>{if(o.isMesh&&!o.layers.isEnabled(31))n+=Array.isArray(o.material)?o.geometry.groups.length:Number(o.material.visible);});return n;};
const build=async(p,k=input.kit)=>{const t=buildTwin(p,k,'low',{viewing:true});await t.ready;return t;};
const original=await build(input.plan),same=structuredClone(input.plan);
const target=same.buildings[0].walls.find(w=>w.exterior&&w.footprint?.length===4);
assert.ok(target,'real household exterior wall');
const {createHash}=await import('node:crypto');
const appearance=root=>{const h=createHash('sha256'),parts=[];root.traverse(o=>{
 if(!o.isMesh||o.layers.isEnabled(31))return;
 const g=o.geometry,ids=g.index?.array||Array.from({length:g.attributes.position.count},(_,i)=>i);
 const mat=[o.material.name,o.material.color.getHex(),o.material.userData.materialKey||null];
 for(let i=0;i<ids.length;i+=3)parts.push(JSON.stringify([mat,Array.from(ids.slice(i,i+3),j=>
  ['position','normal','uv'].map(name=>{const a=g.attributes[name];return a?Array.from({length:a.itemSize},(_,c)=>a.getComponent(j,c)):null;}))]));
 });h.update(parts.sort().join('\n'));return h.digest('hex');};
const originalAppearance=appearance(original.root);
// Trying either side exercises the exterior ref without assuming footprint winding.
let shared=null;
for(const side of ['left','right']){
 target.faces={[side]:{...same.buildings[0].materials.siding}};
 const got=await build(same);
 if(calls(got.root)===calls(original.root)&&appearance(got.root)===originalAppearance){shared=got;break;}
}
assert.ok(shared,'same-as-building wall face adds no household draw submission');
const signatures=t=>new Set([...t.materials.values()].filter(m=>m.name==='siding').map(m=>m.userData.materialKey||JSON.stringify([m.name,m.color.getHex(),m.roughness,m.metalness])));
assert.deepEqual(signatures(shared),signatures(original));
console.log('ok household same-as-default wall keeps '+calls(original.root)+' structure draws');
const square=(x,y,w=12,h=w)=>[[x,y],[x+w,y],[x+w,y+h],[x,y+h]];
const section={id:'r',kind:'hip',ridge:'x',rect:[0,0,12,12],plate:8,pitch:6,overhang:0,
 plane_edges:{y0:0,x1:1,y1:2,x0:3}};
const roofBase=roofMesh([section]);
assert.equal(new Set(roofBase.edge).size,4);
for(let i=0;i<roofBase.section.length;i++){
 assert.equal(roofBase.section[i],0);
 assert.equal(roofBase.edge[i],section.plane_edges[roofBase.side[i]]);
}
const entry=color=>({kind:'material',household:true,revision:1,maps:{},params:{tint:color,tile_ft:[4,4]}});
const custom=structuredClone(input.kit);custom.manifest={};
for(let i=0;i<4;i++)custom.manifest['slope'+i]=entry(['#ff0000','#00ff00','#0000ff','#ffff00'][i]);
const basic={id:'b',position:[0,0],rotation:0,base:0,materials:{},
 levels:[{id:'l',elevation:0,ceiling:8,outline:square(0,0)}],walls:[],openings:[],
 rooms:[{id:'a',level:'l',polygon:square(0,0,6,12)},{id:'b',level:'l',polygon:square(6,0,6,12)}],
 roof:{sections:[section],flags:[]},roofs:[],items:[],stairs:[],fixtures:[],anchors:[],lights:[]};
const p={materials:{},buildings:[basic],site:{}};
basic.roof.sections[0].plane_materials=Object.fromEntries([0,1,2,3].map(i=>[i,{id:'slope'+i}]));
const four=await build(p,custom),roofMaterials=new Set();
four.root.traverse(o=>{if(o.isMesh&&o.material.name==='roof'&&o.material.userData.materialId)roofMaterials.add(o.material.userData.materialId);});
assert.deepEqual([...roofMaterials].sort(),['slope0','slope1','slope2','slope3']);
assert.deepEqual(Array.from(four.roofSurfaces.get('b').positions),Array.from(roofBase.positions));
const keyBeforeRevision=buildingKey(p,basic,custom,'low');custom.manifest.slope0.revision++;
assert.notEqual(buildingKey(p,basic,custom,'low'),keyBeforeRevision,'roof plane Library revisions rebuild retained structure');
const byLevel=structuredClone(p);delete byLevel.buildings[0].roof.sections[0].plane_materials;
byLevel.buildings[0].levels[0].materials={roof:{id:'slope2'}};
const levelRoof=await build(byLevel,custom),levelRoofIds=new Set();
levelRoof.root.traverse(o=>{if(o.isMesh&&o.material.name==='roof')levelRoofIds.add(o.material.userData.materialId);});
assert.deepEqual([...levelRoofIds],['slope2'],'roof defaults resolve through their owning floor');
const partialCeiling=structuredClone(p);partialCeiling.buildings[0].rooms[0].ceiling_material={uv:{u:.1,v:0,rot:90}};
const ceilingTwin=await build(partialCeiling,custom),ceilingParts=[];
ceilingTwin.root.traverse(o=>{if(o.isMesh&&o.userData.part==='ceiling')ceilingParts.push(o);});
assert.ok(ceilingParts.length>0);assert.ok(ceilingParts.every(o=>o.material.name==='ceramic'&&o.material.color.getHexString()==='f4f4f2'),
 'id-less ceiling UV inherits the built-in finish');
// Coplanar overlapping sections: the disjoint union must cover every interior
// sample once, with each section owning its nearest-centre territory.
const roofA={...section,id:'left',kind:'shed',low_side:'y0',rect:[0,0,10,12]},roofB={...roofA,id:'right',rect:[6,0,16,12]};
const overlap=roofMesh([roofA,roofB],{materialKey:f=>'material'+f.section});
const cross=(a,b,q)=>(b[0]-a[0])*(q[1]-a[1])-(b[1]-a[1])*(q[0]-a[0]);
for(let x=.173;x<16;x+=.41)for(let y=.219;y<12;y+=.43){
 const hits=[];
 for(let t=0;t<overlap.section.length;t++){
  const v=[0,3,6].map(j=>Array.from(overlap.positions.slice(t*9+j,t*9+j+3)));
  if(v.every((a,i)=>cross(a,v[(i+1)%3],[x,y])>1e-7))hits.push(overlap.section[t]);
 }
 assert.equal(hits.length,1,'exact coverage, no gap or coplanar z-fight at '+[x,y]);
 assert.equal(hits[0],x<8?0:1,'own section finish across shared plane');
}
const tripleSections=[roofA,roofB,{...roofA,id:'middle',rect:[2,0,14,12]}];
const triple=roofMesh(tripleSections,{materialKey:f=>f.section===2?'other':'same'});
const coincident=roofMesh([{...roofA,id:'alpha'},{...roofA,id:'beta'}],{materialKey:f=>'different'+f.section});
assert.deepEqual([...new Set(coincident.section)].sort(),[0,1],'coincident footprints retain both plane finishes');
for(let x=.173;x<16;x+=.41)for(let y=.219;y<12;y+=.43){
 const hits=[];
 for(let t=0;t<triple.section.length;t++){
  const v=[0,3,6].map(j=>Array.from(triple.positions.slice(t*9+j,t*9+j+3)));
  if(v.every((a,i)=>cross(a,v[(i+1)%3],[x,y])>1e-7))hits.push(triple.section[t]);
 }
 assert.equal(hits.length,1,'three coplanar sections have no cyclic ownership gap');
}
const joinedPlan=structuredClone(p);joinedPlan.buildings[0].roof.sections=[
 {...roofA,plane_materials:{0:{id:'slope0'}}},{...roofB,plane_materials:{0:{id:'slope1'}}}];
const joined=await build(joinedPlan,custom);let internalBands=0;
joined.root.traverse(o=>{if(!o.isMesh||o.layers.isEnabled(31)||o.material.name!=='roof')return;
 const pos=o.geometry.attributes.position,n=o.geometry.attributes.normal,idx=o.geometry.index?.array||Array.from({length:pos.count},(_,i)=>i);
 for(let i=0;i<idx.length;i+=3){const tri=Array.from(idx.slice(i,i+3));
  if(tri.every(j=>Math.abs(pos.getX(j)-8)<1e-6)&&Math.abs(n.getY(tri[0]))<.1)internalBands++;
 }
});
assert.equal(internalBands,0,'no coincident thickness bands at the coplanar material seam');
console.log('ok four plane finishes, triangle labels and coplanar vertex coverage');
// Canonical per-piece UV rows survive batching, which may reorder materials.
const rows=root=>{const result=[];root.traverse(o=>{
 if(!o.isMesh||o.layers.isEnabled(31))return;
 const g=o.geometry,uv=g.attributes.uv,pos=g.attributes.position,n=g.attributes.normal;
 const ids=g.index?.array||Array.from({length:pos.count},(_,i)=>i);
 const ranges=o.userData.snapRanges||[{pieceId:o.userData.pieceId,start:0,count:ids.length}];
 for(const r of ranges)for(let i=r.start;i<r.start+r.count;i++){
  const j=ids[i];result.push({key:JSON.stringify([r.pieceId,o.material.name,[pos.getX(j),pos.getY(j),pos.getZ(j)],[n?.getX(j),n?.getY(j),n?.getZ(j)]]),
   piece:r.pieceId,uv:uv?[uv.getX(j),uv.getY(j)]:null,program:o.material.customProgramCacheKey()});
 }
 });return result.sort((a,b)=>a.key.localeCompare(b.key)||JSON.stringify(a.uv).localeCompare(JSON.stringify(b.uv)));};
const floors=structuredClone(p);floors.buildings[0].roof.sections=[];
const a=await build(floors,custom);floors.buildings[0].rooms[0].floor_material={uv:{u:.25,v:.5,rot:90}};
const shifted=await build(floors,custom),ra=rows(a.root),rb=rows(shifted.root);
assert.equal(ra.length,rb.length);let changes=0;
for(let i=0;i<ra.length;i++){
 assert.equal(ra[i].key,rb[i].key);assert.equal(ra[i].program,rb[i].program);
 if(ra[i].piece==='a'&&ra[i].key.includes('"floor"')){if(JSON.stringify(ra[i].uv)!==JSON.stringify(rb[i].uv))changes++;}
 else assert.deepEqual(ra[i].uv,rb[i].uv,'only the chosen floor moves');
}
assert.ok(changes>0);assert.equal(calls(a.root),calls(shifted.root));
console.log('ok real generator isolates one floor UV, preserves instances and program keys');
const wallPlan=structuredClone(input.plan);wallPlan.buildings[0].walls.find(w=>w.id===target.id).faces={right:{uv:{u:.25,v:.5,rot:90}}};
const movedWall=await build(wallPlan),wa=rows(original.root),wb=rows(movedWall.root);let wallChanges=0;
assert.equal(wa.length,wb.length);
for(let i=0;i<wa.length;i++){
 assert.equal(wa[i].key,wb[i].key);assert.equal(wa[i].program,wb[i].program);
 if(wa[i].piece===target.id){if(JSON.stringify(wa[i].uv)!==JSON.stringify(wb[i].uv))wallChanges++;}
 else assert.deepEqual(wa[i].uv,wb[i].uv,'household wall UV touches only the chosen wall');
}
assert.ok(wallChanges>0,'footprint wall faces carry their explicit UV through batching');
assert.equal(calls(original.root),calls(movedWall.root));
console.log('ok household footprint wall UV, unchanged neighbours and no extra batch');
const poolPlan={materials:{},buildings:[],site:{pool:{id:'pool',polygon:square(0,0,30,20),depth:5,coping:1,
 materials:{interior:{id:'slope0'},coping:{id:'slope1'}},features:[
 {id:'ledge',kind:'ledge',polygon:square(1,1,4,4),materials:{interior:{id:'slope2'},coping:{id:'slope3'}}},
 {id:'steps',kind:'steps',polygon:square(7,1,4,6),treads:3,materials:{interior:{id:'slope3'},coping:{id:'slope2'}}}]}}};
const poolYard=(await buildYard(poolPlan,custom,'low')).group;
const featureIds=new Map();poolYard.traverse(o=>{if(!o.isMesh)return;for(const r of o.userData.snapRanges||[])if(['ledge','steps'].includes(r.pieceId)){
 if(!featureIds.has(r.pieceId))featureIds.set(r.pieceId,new Set());featureIds.get(r.pieceId).add(o.material.userData.materialId);
}});
for(const id of ['ledge','steps'])assert.deepEqual([...featureIds.get(id)].sort(),['slope2','slope3']);
const movedPool=structuredClone(poolPlan);movedPool.site.pool.features[0].materials.interior.uv={u:.25,v:.5,rot:90};
const movedPoolYard=(await buildYard(movedPool,custom,'low')).group,pa=rows(poolYard),pb=rows(movedPoolYard);let poolChanges=0;
assert.equal(pa.length,pb.length);
for(let i=0;i<pa.length;i++){
 assert.equal(pa[i].key,pb[i].key);assert.equal(pa[i].program,pb[i].program);
 if(pa[i].piece==='ledge'){if(JSON.stringify(pa[i].uv)!==JSON.stringify(pb[i].uv))poolChanges++;}
 else assert.deepEqual(pa[i].uv,pb[i].uv,'ledge offset leaves every pool/step neighbour unchanged');
}
assert.ok(poolChanges>0);assert.equal(calls(poolYard),calls(movedPoolYard));
const inheritPool=structuredClone(poolPlan);for(const f of inheritPool.site.pool.features)delete f.materials;
const inheritedYard=(await buildYard(inheritPool,custom,'low')).group,inheritedIds=new Map();
inheritedYard.traverse(o=>{if(!o.isMesh)return;for(const r of o.userData.snapRanges||[])if(['ledge','steps'].includes(r.pieceId)){
 if(!inheritedIds.has(r.pieceId))inheritedIds.set(r.pieceId,new Set());inheritedIds.get(r.pieceId).add(o.material.userData.materialId);
}});
for(const id of ['ledge','steps'])assert.deepEqual([...inheritedIds.get(id)].sort(),['slope0','slope1'],'feature follows pool slots');
const tintOnly={materials:{pool_coping:{color:'#abcdef'}},buildings:[],site:{pool:{id:'pool',polygon:square(0,0,20),
 features:[{id:'ledge',kind:'ledge',polygon:square(1,1,4)}]}}};
const tintedYard=(await buildYard(tintOnly,custom,'low')).group;let tintedTread=false;
tintedYard.traverse(o=>{if(o.isMesh&&o.material.color.getHexString()==='abcdef'
 && o.userData.snapRanges?.some(r=>r.pieceId==='ledge'))tintedTread=true;});
assert.ok(tintedTread,'a house coping tint with no ID inherits the kit and reaches feature treads');
const offsetOnly=structuredClone(tintOnly);offsetOnly.materials={};
const noCoping=(await buildYard(offsetOnly,custom,'low')).group;
offsetOnly.site.pool.features[0].materials={coping:{uv:{u:.25,v:.5,rot:90}}};
const copingOffset=(await buildYard(offsetOnly,custom,'low')).group;
assert.equal(calls(noCoping),calls(copingOffset),'a coping UV-only ref never activates another material batch');
const rolePlan={materials:{pool_interior:{id:'slope0'},pool_waterline:{id:'slope1'},pool_coping:{id:'slope2'}},buildings:[],site:{pool:{id:'pool',polygon:square(0,0,20),coping:1}}};
const roleYard=(await buildYard(rolePlan,custom,'low')).group,ids=new Set();
roleYard.traverse(o=>{if(o.isMesh&&o.material.userData.materialId)ids.add(o.material.userData.materialId);});
for(const id of ['slope0','slope1','slope2'])assert.ok(ids.has(id),'house-wide pool role '+id);
const keys=yardPartKeys(rolePlan,custom,'low');rolePlan.materials.pool_interior={id:'slope3'};
assert.notEqual(yardPartKeys(rolePlan,custom,'low').pool,keys.pool,'house role invalidates reused pool');
const pavingPlan={materials:{paving:{id:'paving',color:input.kit.materials.paving.color}},buildings:[],site:{hardscape:[
 {id:'one',kind:'patio',polygon:square(0,0,4),material:'paving'},{id:'two',kind:'patio',polygon:square(6,0,4),material:'paving'}]}};
const pavingDefault=(await buildYard(pavingPlan,input.kit,'low')).group;
pavingPlan.site.hardscape[0].materials={surface:{...pavingPlan.materials.paving}};
const pavingOverride=(await buildYard(pavingPlan,input.kit,'low')).group;
assert.equal(calls(pavingOverride),calls(pavingDefault),'same procedural yard default and tint share their batch');
console.log('ok ledge/steps parts, pool inheritance, house-wide pool roles and reuse keys');
"""


def payload():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = bridge.assemble(fixture)[0]
    plan = bridge.flatten(model)
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    mappings = []
    for building in model['buildings']:
        for roof in building.get('roofs', []):
            for section in twin_model_roofs.to_sections(roof):
                mappings.append({'area': roof['area'], 'rect': section['rect'],
                                 'expected': twin_model_roofs._rectangle_edge_indices(roof, section['rect'])})
    return {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit, 'mappings': mappings}


if __name__ == '__main__':
    code, output = run_node(DRIVER, payload(), timeout=300)
    print(output)
    sys.exit(code or 0)
