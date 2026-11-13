"""Real generator, material reuse, terrain, bake and porch shelf under Node."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import(three);
const {createHash}=await import('node:crypto');
const {buildTwin}=await import(file('static/twin/twin_generator.js'));
const {groundAt,buildingBase}=await import(file('static/twin/twin_ground.js'));
const {insetPorch,porchFoundationRole,PORCH_SLAB_FT}=await import(file('static/twin/twin_porch_foundation.js'));
const {atlasJob,covered}=await import(file('static/twin/bake/atlas_transport.js'));
const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
const {disposeObject}=await import(file('static/twin/twin_library.js'));
const near=(a,b,why='')=>assert.ok(Math.abs(a-b)<2e-5,`${why}: ${a} != ${b}`);
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
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
// Captured from the original v2.499.819 generator before this feature.
assert.equal(baselineDigest,'c87d6a6e00d4792ee7fc2081e06363fed7fbab9cdc6259fb4c97e8f73a0a5fd0','posts fixture is byte-identical to the pre-feature generator');
po.foundation={type:'posts',material:'brick',lip_in:4};
const posts=build();await posts.ready;assert.equal(geometryDigest(posts),baselineDigest,'explicit posts ignores solid-only settings');
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
// Actual cards run with a DOM double, saving through the operation queue.
const {createCards}=await import(file('static/twin/editor/cards.js'));
const room=b.rooms[0];room.foundation={type:'posts',material:'stone',lip_in:1};let writable=true;
const calls=[],errors=[];window.showGlobalAlert=message=>errors.push(message);
const cards=createCards({getPlan:()=>plan,getLabel:()=> 'Porch',canEdit:()=>writable,edit(){},op:async operation=>{
 calls.push(operation);room.foundation=operation.foundation;},ask(){},select(){}});
cards.draw({pieceId:'porch',buildingId:'b'});const shelf=document.getElementById('piece-card');
const field=label=>shelf.querySelectorAll('input, select').find(e=>e.getAttribute('aria-label')===label);
assert.ok(!shown(field('Foundation material')));field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});
assert.equal(calls.at(-1).op,'set_porch_foundation');assert.ok(shown(field('Foundation material')));
const sameCount=calls.length;await fire(field('Foundation material'),'change');await cards.queue(async()=>{});assert.equal(calls.length,sameCount,'same material is not another undo step');
field('Foundation material').value='brick';await fire(field('Foundation material'),'change');await cards.queue(async()=>{});
field('Floor overhang (in)').value='2.5';await fire(field('Floor overhang (in)'),'change');await cards.queue(async()=>{});
assert.deepEqual(room.foundation,{type:'solid',material:'brick',lip_in:2.5});
const count=calls.length;field('Floor overhang (in)').value='5';await fire(field('Floor overhang (in)'),'change');await cards.queue(async()=>{});
assert.equal(calls.length,count);assert.equal(errors.length,1);
room.foundation={type:'posts',material:'stone',lip_in:1};cards.draw();assert.equal(field('Foundation').value,'posts');assert.ok(!shown(field('Foundation material')),'undo refreshes shelf');
writable=false;cards.draw();assert.ok(field('Foundation').disabled);field('Foundation').value='solid';await fire(field('Foundation'),'change');await cards.queue(async()=>{});assert.equal(calls.length,count);
console.log('Passed: golden posts, slope/step plinth, inset, roof supports, roles, bake keys/UVs/tiers, materials, offset/auto-base, shelf/undo/read-only');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
