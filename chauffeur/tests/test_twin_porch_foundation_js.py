"""Real generator, material reuse, terrain, bake and porch shelf under Node."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node
from twin_solid_normals import NORMAL_CHECKS

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + NORMAL_CHECKS + r"""
const THREE=await import(three);
const {createHash}=await import('node:crypto');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {groundAt,buildingBase}=await import(file('static/twin/twin_ground.js'));
const {insetPorch,porchPlinthGeometry,porchFoundationRole,PORCH_SLAB_FT,POST_SLAB_FT,PORCH_BEAM_FT,porchFoundation,porchOnGrade,porchSupportGeometry}=await import(file('static/twin/twin_porch_foundation.js'));
const {atlasJob,covered}=await import(file('static/twin/bake/atlas_transport.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const near=(a,b,why='')=>assert.ok(Math.abs(a-b)<2e-5,`${why}: ${a} != ${b}`);
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
// Test actual triangle winding: lighting normals alone cannot prove FrontSide visibility.
for(const [label,polygon] of [
 ['CCW rectangle',square(0,-6,10,0)],['CW rectangle',square(0,-6,10,0).reverse()],
 ['L-shaped porch',[[0,-6],[10,-6],[10,-2],[4,-2],[4,0],[0,0]]],
 ['CW L-shaped porch',[[0,0],[4,0],[4,-2],[10,-2],[10,-6],[0,-6]]]]){
 const porch={polygon,foundation:{lip_in:1}},outline=insetPorch(polygon,1/12);
 const geometry=porchPlinthGeometry({site:{terraces:[]}}, {}, porch,1.75,0);
 checkBoundaryNormals(geometry,outline,{top:1.75,bottom:0,label});
 const material=new THREE.MeshBasicMaterial({side:THREE.FrontSide}),mesh=new THREE.Mesh(geometry,material);
 const hits=new THREE.Raycaster(new THREE.Vector3(2,1,9),new THREE.Vector3(0,0,-1)).intersectObject(mesh);
 assert.ok(hits.length,`${label}: front is visible from outside`);
 near(-hits[0].point.z,-6+1/12,`${label}: first hit is inset front edge`);
 assert.ok(hits[0].face.normal.z>0,`${label}: front normal faces the ray`);
 geometry.dispose();material.dispose();
}
console.log('Passed: outward porch sides, up/down caps and FrontSide front raycast (rectangle and L, both windings)');
const po={id:'porch',polygon:square(0,-6,10,0),floor:2,columns:[{at:[.5,-5.5],size:.5},{at:[9.5,-5.5],size:.5}]};
const b={id:'b',position:[7,-3],rotation:27,base:3,levels:[{id:'L1',elevation:0,ceiling:10,outline:square(0,0,10,10)},
 {id:'L2',elevation:10,ceiling:8,outline:square(0,0,10,10)}],walls:[],rooms:[],openings:[],
 roof:{sections:[{id:'roof',kind:'shed',rect:[0,-6,10,10],plate:10,pitch:2,overhang:0,low_side:'y0'}]},porches:[po],stairs:[],anchors:[],items:[]};
const plan={units:'ft',materials:{},buildings:[b],site:{terraces:[]}};
const build=(p=plan,tier='low',reuseMaterials)=>buildTwin(p,input.kit,tier,{viewing:true,editableLevel:'b:L1',reuseMaterials});
const geometryDigest=out=>{const hash=createHash('sha256');out.root.traverse(o=>{
 if(!o.isMesh||o.layers.isEnabled(31))return;hash.update(o.material.name);
 for(const key of Object.keys(o.geometry.attributes).sort())hash.update(Buffer.from(o.geometry.attributes[key].array.buffer));
 if(o.geometry.index)hash.update(Buffer.from(o.geometry.index.array.buffer));
 });return hash.digest('hex');};
const before=build();await before.ready;
const baselineDigest=geometryDigest(before);
console.log('Posts fixture digest:',baselineDigest);
// Missing foundations now build real piers, just like explicit default posts.
po.foundation={type:'posts'};
const posts=build();await posts.ready;assert.equal(geometryDigest(posts),baselineDigest);
po.foundation={type:'solid',material:'stone',lip_in:1};
const goldenSolid=build();await goldenSolid.ready;
assert.equal(geometryDigest(goldenSolid),'11bf1f94fd04080ec5c5bedd112e189888579310ac350b119b9e06f5d4faf459',
 'solid fixture is byte-identical to the shipped generator');
const goldenPlinth=porchPlinthGeometry({site:{terraces:[]}}, {}, {polygon:square(0,-6,10,0),foundation:{lip_in:1}},1.75,0);
const gh=createHash('sha256');for(const key of Object.keys(goldenPlinth.attributes).sort())gh.update(Buffer.from(goldenPlinth.attributes[key].array.buffer));
assert.equal(gh.digest('hex'),'4c4738591318f9c31de569b73e85261ad9944953bc6e661dfa9b8206cdf48067');
goldenPlinth.dispose();
const angle=b.rotation*Math.PI/180;
const world=p=>[b.position[0]+Math.cos(angle)*p[0]-Math.sin(angle)*p[1],b.position[1]+Math.sin(angle)*p[0]+Math.cos(angle)*p[1]];
// A sloped layer and a sharp nested layer cross the rotated porch.
plan.site.terraces=[{id:'yard',polygon:square(-30,-30,30,-7),height:-3,blend:12},
 {id:'step',polygon:square(10,-30,12,30),height:-1,blend:0}];
po.foundation={type:'solid',material:'stone',lip_in:1};
const solid=build();await solid.ready;
const plinths=solid.pieces.get('b:porch').filter(o=>o.isMesh&&o.material.name==='base');
assert.ok(plinths.length);assert.ok(plinths.every(o=>covered(solid.root).includes(o)&&o.receiveShadow));
const outline=insetPorch(po.polygon,1/12),top=po.floor-PORCH_SLAB_FT;
outline.flat().forEach((v,i)=>near(v,[[1/12,-6+1/12],[10-1/12,-6+1/12],[10-1/12,-1/12],[1/12,-1/12]].flat()[i]));
assert.deepEqual(insetPorch([...po.polygon].reverse(),1/12),outline);
const closed=insetPorch([...po.polygon,po.polygon[0]],1/12);
assert.equal(closed.length,4);assert.ok(closed.every(p=>outline.some(q=>Math.hypot(p[0]-q[0],p[1]-q[1])<1e-8)));
const concave=[[0,0],[10,0],[10,4],[4,4],[4,10],[0,10]];
assert.deepEqual(insetPorch(concave,.25),[[.25,.25],[9.75,.25],[9.75,3.75],[3.75,3.75],[3.75,9.75],[.25,9.75]]);
for(const lip of [0,4/12])assert.ok(insetPorch([[0,0],[10,2],[8,8],[-2,6]],lip).flat().every(Number.isFinite));
const boundary=p=>Math.abs(p[0]-outline[0][0])<1e-5||Math.abs(p[0]-outline[1][0])<1e-5||Math.abs(p[1]-outline[0][1])<1e-5||Math.abs(p[1]-outline[2][1])<1e-5;
const heights=new Map();let bottomCount=0,topCount=0;
for(const mesh of plinths){assert.equal(mesh.parent.userData.levelKey,'b:L1','base belongs to the lowest floor peel/cut domain');
 const p=mesh.geometry.attributes.position,n=mesh.geometry.attributes.normal;
 for(let i=0;i<p.count;i++){
  const x=p.getX(i),y=-p.getZ(i),h=p.getY(i);assert.ok(h<=top+1e-5);
  if(Math.abs(h-top)<1e-5){topCount++;continue;}
  if(!boundary([x,y]))continue;bottomCount++;
  const [wx,wy]=world([x,y]);const expected=groundAt(plan,wx,wy)-b.base;
  // At a terrace step there are two legitimate one-sided ground heights.
  const adjacent=[expected,...[[1e-5,0],[-1e-5,0],[0,1e-5],[0,-1e-5]].map(([dx,dy])=>groundAt(plan,wx+dx,wy+dy)-b.base)];
  assert.ok(adjacent.some(v=>Math.abs(h-v)<3e-5),`bottom ${x},${y},${h} follows ground ${adjacent}`);
  const key=`${x.toFixed(4)},${y.toFixed(4)}`;if(!heights.has(key))heights.set(key,new Set());heights.get(key).add(h.toFixed(3));
 }
}
assert.ok(bottomCount>20&&topCount>5);assert.ok([...heights.values()].some(v=>v.size>1),'step has a vertical skirt instead of a ramp');
const roofPosts=solid.pieces.get('b:porch').filter(o=>o.isMesh&&o.material.name==='trim');assert.ok(roofPosts.length);
for(const o of roofPosts){
 const p=o.geometry.attributes.position;assert.ok([...Array(p.count).keys()].every(i=>p.getY(i)>=po.floor-1e-5),'no below-floor posts');
 assert.ok([...Array(p.count).keys()].some(i=>p.getY(i)>po.floor+3),'roof-support posts remain');
}
const slab=solid.pieces.get('b:porch').find(o=>o.isMesh&&o.material.name==='patio_concrete');
slab.geometry.computeBoundingBox();near(slab.geometry.boundingBox.min.y,top);near(slab.geometry.boundingBox.max.y,po.floor);
const options={room:{density:1,page:256,gutter:2}};
const postsPlan=structuredClone(plan);postsPlan.buildings[0].porches[0].foundation.type='posts';
const postTerrain=build(postsPlan);await postTerrain.ready;
assert.notEqual(atlasJob(solid.root,plan,options).cacheKey,atlasJob(postTerrain.root,postsPlan,options).cacheKey);
const atlas=buildAtlas(solid.root,plan,options);
assert.ok(plinths.every(m=>m.geometry.attributes.uv3),'plinth receives baked-light UVs');
const high=build(plan,'high');await high.ready;
assert.equal(buildAtlas(high.root,plan,options).key,atlas.key,'solid porch bakes identically on every tier');
// Existing stairs still start at grade and meet the unchanged deck edge.
const steppedPlan=structuredClone(plan),sb=steppedPlan.buildings[0];
sb.position=[0,0];sb.rotation=0;sb.base=0;steppedPlan.site.terraces=[];
sb.stairs=[{id:'steps',level:'L1',from:[4,-10],to:[4,-6],width:4,risers:4,rise_to:po.floor}];
const solidSteps=build(steppedPlan);await solidSteps.ready;
sb.porches[0].foundation.type='posts';const postSteps=build(steppedPlan);await postSteps.ready;
const stairPositions=o=>o.pieces.get('b:steps').flatMap(m=>[...m.geometry.attributes.position.array]);
assert.deepEqual(stairPositions(solidSteps),stairPositions(postSteps));
const stairBounds=new THREE.Box3();for(const o of solidSteps.pieces.get('b:steps')){o.geometry.computeBoundingBox();stairBounds.union(o.geometry.boundingBox);}
near(stairBounds.min.y,0);near(stairBounds.max.y,po.floor);near(stairBounds.min.z,6);
let prior=solid;
for(const material of ['brick','concrete','stone','brick']){
 po.foundation.material=material;
 const next=build(plan,'low',prior.materials);await next.ready;
 const role=porchFoundationRole(material);assert.ok(next.pieces.get('b:porch').some(o=>o.material?.name===role));
 const repeat=build(plan,'low',next.materials);await repeat.ready;
 assert.equal(repeat.materials.size,next.materials.size);for(const [key,value] of repeat.materials)assert.equal(value,next.materials.get(key),'no material per rebuild');
 prior=repeat;
}
// Offset/auto-base and room-backed porches meet at the same slab underside.
b.rooms=[{id:'porch',kind:'porch',level:'L1',polygon:po.polygon,floor_offset_ft:-.5}];
b.foundation={mode:'auto',offset_ft:3,thickness_ft:1};
const roomSolid=build();await roomSolid.ready;
const roomSlab=roomSolid.pieces.get('b:porch').find(o=>o.material?.name==='patio_concrete');
roomSlab.geometry.computeBoundingBox();near(roomSlab.geometry.boundingBox.min.y,po.floor-.5-PORCH_SLAB_FT);
// Runtime support layout, terrain contact, floor slab and skirt construction.
const testPlan=structuredClone(plan),tb=testPlan.buildings[0],tp=tb.porches[0];
tb.rooms=[];tb.foundation={mode:'fixed'};tb.base=0;tb.position=[0,0];tb.rotation=0;testPlan.site.terraces=[];
tp.foundation={type:'posts',post_in:6,post_shape:'square',spacing_ft:4,lip_in:1};
const support=porchSupportGeometry(testPlan,tb,tp,tp.floor,0);
assert.equal(support.posts.length,10,'3 intervals on long edges, 2 on short edges, corners once');
assert.equal(new Set(support.posts.map(p=>p.at.join(','))).size,10);
for(const corner of support.outline)assert.ok(support.posts.some(p=>Math.hypot(p.at[0]-corner[0],p.at[1]-corner[1])<1e-6));
for(let i=0;i<support.posts.length;i++){
 const p=support.posts[i],q=support.posts[(i+1)%support.posts.length];
 assert.ok(Math.hypot(p.at[0]-q.at[0],p.at[1]-q.at[1])<=4+1e-6);
 near(p.bottom,0);near(p.top,tp.floor-4/12);
}
near(support.slabBottom-support.beamBottom,8/12);
// Check actual vertices and FrontSide bottom contact, not just layout metadata.
const sm=new THREE.Mesh(support.supports,new THREE.MeshBasicMaterial({side:THREE.FrontSide}));
for(const p of support.posts){
 const hit=new THREE.Raycaster(new THREE.Vector3(p.at[0],-10,-p.at[1]),new THREE.Vector3(0,1,0)).intersectObject(sm)[0];
 assert.ok(hit);near(hit.point.y,p.bottom);assert.ok(hit.face.normal.y<0);
}
for(const {vertices,normal,centre} of trianglesOf(support.supports)){
 if(Math.abs(normal.y)<1e-6&&vertices.every(v=>v.y<support.beamBottom-1e-5)){
  const p=support.posts.reduce((best,p)=>Math.hypot(centre.x-p.at[0],-centre.z-p.at[1])<Math.hypot(centre.x-best.at[0],-centre.z-best.at[1])?p:best);
  assert.ok(normal.dot(new THREE.Vector3(centre.x-p.at[0],0,centre.z+p.at[1]))>0,'post side faces outward');
 }
}
const open=build(testPlan);await open.ready;
const deck=open.pieces.get('b:porch').find(o=>o.material?.name==='patio_concrete');deck.geometry.computeBoundingBox();
near(deck.geometry.boundingBox.min.y,tp.floor-4/12);near(deck.geometry.boundingBox.max.y,tp.floor);
checkBoundaryNormals(deck.geometry,tp.polygon,{top:tp.floor,bottom:tp.floor-4/12,label:'supported porch slab'});
for(const {vertices,normal}of trianglesOf(support.supports)){
 if(vertices.every(v=>Math.abs(v.y-support.slabBottom)<1e-5))assert.ok(normal.y>0,'post/beam top faces up');
 if(vertices.every(v=>Math.abs(v.y-support.beamBottom)<1e-5))assert.ok(normal.y<0,'rim underside faces down');
}
assert.equal(support.skirt,null,'posts have no skirt');
const centreRay=new THREE.Raycaster(new THREE.Vector3(5,-1,3),new THREE.Vector3(0,1,0));
assert.equal(centreRay.intersectObject(sm).length,0,'interior below porch is air');
for(const polygon of [square(0,-6,10,0).reverse(),[[0,0],[10,0],[10,4],[4,4],[4,10],[0,10]]]){
 const porch={polygon,foundation:{type:'posts',spacing_ft:4}},g=porchSupportGeometry(testPlan,tb,porch,2,0);
 for(const corner of g.outline)assert.ok(g.posts.some(p=>Math.hypot(p.at[0]-corner[0],p.at[1]-corner[1])<1e-6),'every inset corner has a pier');
 for(let i=0;i<g.posts.length;i++)assert.ok(Math.hypot(...g.posts[i].at.map((v,k)=>v-g.posts[(i+1)%g.posts.length].at[k]))<=4+1e-6);
 g.supports.dispose();
}
// Sloped and layered pads, with building rotation and base applied per pier.
testPlan.site.terraces=[{polygon:square(-20,-20,2,20),height:-3,blend:12},{polygon:square(5,-8,7,8),height:-1,blend:0}];
tb.position=[1,-1];tb.rotation=18;tb.base=2;
for(const shape of ['square','round']){
 tp.foundation.post_shape=shape;
 const g=porchSupportGeometry(testPlan,tb,tp,tp.floor,tb.base),mesh=new THREE.Mesh(g.supports,sm.material);
 const a=tb.rotation*Math.PI/180;
 for(const p of g.posts){
  const wx=tb.position[0]+Math.cos(a)*p.at[0]-Math.sin(a)*p.at[1],wy=tb.position[1]+Math.sin(a)*p.at[0]+Math.cos(a)*p.at[1];
  near(p.bottom,groundAt(testPlan,wx,wy)-tb.base);
  const hit=new THREE.Raycaster(new THREE.Vector3(p.at[0],-20,-p.at[1]),new THREE.Vector3(0,1,0)).intersectObject(mesh)[0];
  assert.ok(hit);near(hit.point.y,p.bottom);
 }
 g.supports.dispose();
}
// Enclosures stay at the perimeter, split exactly at pad boundaries, one merged skirt.
tb.position=[0,0];tb.rotation=0;tb.base=0;
testPlan.site.terraces=[{polygon:square(-20,-20,20,20),height:-2,blend:0},{polygon:square(4,-20,6,20),height:-1,blend:0}];
tp.foundation={...tp.foundation,type:'enclosed',post_shape:'square'};
const stats={};
for(const skirt of ['panel','lattice']){
 tp.foundation.skirt=skirt;
 const g=porchSupportGeometry(testPlan,tb,tp,tp.floor,0),mesh=new THREE.Mesh(g.skirt,sm.material);
 assert.equal(g.spans.length,g.posts.length,'one skirt span between every pair of neighbouring posts');
 assert.ok(g.skirt&&!g.skirt.groups.length,'all strips/panels merged for one draw call');
 near(Math.max(...Array.from(g.skirt.attributes.position.array).filter((_,i)=>i%3===1)),g.beamBottom);
 assert.equal(centreRay.intersectObject(mesh).length,0,'skirt leaves interior empty');
 let hits=0,gaps=0;
 for(let x=.7;x<9.3;x+=.07){
  const hit=new THREE.Raycaster(new THREE.Vector3(x,.5,8),new THREE.Vector3(0,0,-1),0,3).intersectObject(mesh)[0];
  if(hit){hits++;assert.ok(hit.face.normal.z>0,'skirt front faces outward');}else gaps++;
 }
 assert.ok(hits>0);if(skirt==='lattice')assert.ok(gaps>hits,'diagonal lattice has real see-through gaps');else assert.ok(hits>gaps*4,'panel is continuous between posts');
 // Both one-sided ground heights exist at a sharp layer step, never bridged by a ramp.
 const pos=g.skirt.attributes.position;
 if(skirt==='panel')for(const x of [4,6])for(const height of [-2,-1])assert.ok(Array.from({length:pos.count},(_,i)=>i).some(i=>Math.abs(pos.getX(i)-x)<1e-5&&Math.abs(pos.getY(i)-height)<1e-5),`skirt ${skirt} reaches x=${x} height=${height}`);
 for(const {vertices}of trianglesOf(g.skirt)){
  if(vertices.every(v=>v.z>5 || v.z<1))for(const x of [4,6])assert.ok(!(Math.min(...vertices.map(v=>v.x))<x-1e-5&&Math.max(...vertices.map(v=>v.x))>x+1e-5),'skirt splits at sharp pad boundaries');
 }
 const scene=build(testPlan);await scene.ready;
 assert.ok(new Set(scene.pieces.get('b:porch').filter(o=>o.isMesh&&!o.layers.isEnabled(31))).size<=4,'bounded porch draw calls');
 stats[skirt]=g;g.supports.dispose();
}
// Ground rule: all corners must be within nine inches (world-space, all types).
for(const type of ['posts','enclosed','solid']){
 tp.foundation.type=type;testPlan.site.terraces=[];tp.floor=.75;
 assert.ok(porchOnGrade(testPlan,tb,tp,tp.floor));
 const onGrade=build(testPlan);await onGrade.ready;
 const below=onGrade.pieces.get('b:porch').filter(o=>o.isMesh&&o.material.name==='trim').flatMap(o=>Array.from(o.geometry.attributes.position.array).filter((_,i)=>i%3===1));
 assert.ok(below.every(y=>y>=tp.floor-1e-5),'no piers/beam when slab on grade');
 tp.floor=.751;assert.ok(!porchOnGrade(testPlan,tb,tp,tp.floor));
 testPlan.site.terraces=[{polygon:square(-20,-20,20,20),height:.1,blend:0}];
 assert.ok(porchOnGrade(testPlan,tb,tp,tp.floor));
}
tp.floor=.7;testPlan.site.terraces=[{polygon:square(-1,-7,1,-5),height:-1,blend:0}];
assert.ok(!porchOnGrade(testPlan,tb,tp,tp.floor),'one corner beyond nine inches prevents slab-on-grade');
// Every authored foundation field and slot affects both bake paths, on every tier.
tp.floor=2;testPlan.site.terraces=[];
tp.foundation={type:'enclosed',lip_in:1,post_in:6,post_shape:'square',spacing_ft:8,skirt:'lattice',materials:{posts:null,skirt:null,solid:null}};
const baseScene=build(testPlan);await baseScene.ready;
const baseKey=atlasJob(baseScene.root,testPlan,options).cacheKey;
for(const [field,value] of Object.entries({type:'posts',lip_in:2,post_in:8,post_shape:'round',spacing_ft:4,skirt:'panel',
 materials:{posts:{id:'trim',color:'#123456'}},})){
 const p=structuredClone(testPlan);p.buildings[0].porches[0].foundation[field]=value;
 const low=build(p);await low.ready;const hi=build(p,'high');await hi.ready;
 assert.notEqual(atlasJob(low.root,p,options).cacheKey,baseKey,field);
 assert.equal(buildAtlas(low.root,p,options).key,buildAtlas(hi.root,p,options).key,`${field}: tiers identical`);
}
for(const slot of ['posts','skirt','solid'])for(const ref of [{id:'base'},{id:'base',color:'#abcdef'}]){
 const p=structuredClone(testPlan);p.buildings[0].porches[0].foundation.materials[slot]=ref;
 const scene=build(p);await scene.ready;assert.notEqual(atlasJob(scene.root,p,options).cacheKey,baseKey,slot);
}
// Same reference across slots and rebuilds is the same cached material instance.
const {materialSlot,kitMaterial}=await import(file('static/twin/twin_library.js'));
const cache=new Map(),role=r=>{if(!cache.has(r))cache.set(r,kitMaterial(r,input.kit,'low'));return cache.get(r);};
const ref={id:'painted_trim',color:'#123456'};
assert.equal(materialSlot(ref,'trim',input.kit,'low',cache,role),materialSlot({...ref},'siding',input.kit,'low',cache,role));
assert.equal(materialSlot(null,'trim',input.kit,'low',cache,role),role('trim'));
const reused=build(testPlan,'low',baseScene.materials);await reused.ready;
for(const [key,value]of baseScene.materials)assert.equal(reused.materials.get(key),value);
console.log('Passed: solid golden digests/normals, terrain/steps, corners/spacing, post shapes/contact, beam/slab, empty enclosure, lattice gaps, draw bound, grade, slots, bake fields/tiers/cache');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
