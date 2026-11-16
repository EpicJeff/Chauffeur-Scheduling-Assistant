"""Fence types through real yard geometry, batching, keys and card events under Node."""
import json
import sys
from pathlib import Path

from test_twin_yard_material_slots_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
# Captured from HEAD before fence types, with the same bent/sloped fixture below.
PLANK_HASH = '686200f6c96d85d85c9e374fda0770b3c60a64404c83f8d1f20ebb87649878ce'

DRIVER = PREFIX + r"""
const THREE=await import('three');
const {createHash}=await import('node:crypto');
const {buildYard,yardKey,yardPartKeys}=await import(file('static/twin/twin_yard.js'));
const {buildFence}=await import(file('static/twin/fence_geometry.js'));
const {drapeGeometry}=await import(file('static/twin/twin_terrain_mesh.js'));
const {groundAt}=await import(file('static/twin/twin_ground.js'));
const {authoredGeometry}=await import(file('static/twin/bake/geometry_key.js'));
const {drawSiteShapeShelf,siteMaterialSlots}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {builtinMaterial}=await import(file('static/twin/surface_kinds.js'));
const {applyMaterialParams}=await import(file('static/twin/twin_library.js'));
const types=['plank','picket','metal','panel'];
const fence={id:'baseline',polyline:[[0,0],[13,0],[17,9]],height:6,elevation:.4};
const plan={buildings:[],site:{fence,terraces:[{polygon:[[3,3],[20,3],[20,20],[3,20]],height:3,blend:8}]}};
const meshes=g=>{const result=[];g.traverse(o=>{if(o.isMesh)result.push(o);});return result;};
const drawn=y=>meshes(y.group).filter(o=>o.userData.yardPart==='fences');
const digest=y=>{const h=createHash('sha256');for(const o of drawn(y)){
 for(const k of ['position','normal','uv'])h.update(new Uint8Array(o.geometry.attributes[k].array.buffer));
 h.update(o.material.name);
}return h.digest('hex');};
const near=(a,b)=>assert.ok(Math.abs(a-b)<2e-5,`${a} near ${b}`);
const bounds=g=>{g.computeBoundingBox();return g.boundingBox;};
const raw=type=>{const out=[];buildFence({...fence,type},(geometry,slot,...seed)=>out.push({geometry,slot,seed}));return out;};
const positions=gs=>gs.flatMap(g=>{const p=g.index?g.toNonIndexed().attributes.position:g.attributes.position;
 return Array.from({length:p.count},(_,i)=>JSON.stringify([p.getX(i),p.getY(i),p.getZ(i)]));}).sort();
const missing=await buildYard(plan,input.kit,'low');
assert.equal(digest(missing),input.plankHash,'plank buffers match the unmodified HEAD');
assert.equal(digest(await buildYard({...plan,site:{...plan.site,fence:{...fence,type:'plank'}}},input.kit,'low')),input.plankHash);
console.log('ok missing type and explicit plank match the pinned HEAD vertex/normal/UV hash');
for(const type of types){
 const p=structuredClone(plan);p.site.fence.type=type;
 const y=await buildYard(p,input.kit,'low');assert.ok(drawn(y).length);
 for(const o of drawn(y))for(const a of Object.values(o.geometry.attributes))assert.ok([...a.array].every(Number.isFinite),type);
 assert.ok(drawn(y).every(o=>o.material.name==='fence'),'all unslotted types keep the fence role');
 if(type!=='plank'){
  const expected=raw(type).map(({geometry})=>drapeGeometry(geometry,p,fence.elevation));
  assert.deepEqual(positions(drawn(y).map(o=>o.geometry)),positions(expected),type+': every piece draped at every vertex');
 }
 const slotted=structuredClone(p);
 slotted.site.fence.materials={boards:{id:'red_brick_03',color:'#112233'},posts:{id:'mocha_oak_veneer',color:'#445566'},rails:{id:'painted_trim',color:'#778899'}};
 const s=await buildYard(slotted,input.kit,'low'),colors=drawn(s).map(o=>o.material.color.getHexString()).sort();
 assert.deepEqual(colors,['112233','445566','778899'],type+': exactly one batch per chosen slot material');
 assert.deepEqual(positions(drawn(s).map(o=>o.geometry)),positions(drawn(y).map(o=>o.geometry)),type+': slots preserve all vertices');
 slotted.site.fence.materials.boards.color='#abcdef';
 const override=drawn(await buildYard(slotted,input.kit,'low'));
 assert.deepEqual(override.map(o=>o.material.color.getHexString()).sort(),['445566','778899','abcdef']);
 const k=yardPartKeys(plan,input.kit,'low'),changed=yardPartKeys(p,input.kit,'low');
 assert.notEqual(k.fences,changed.fences);assert.notEqual(yardKey(plan,input.kit,'low'),yardKey(p,input.kit,'low'));
 for(const name of Object.keys(k))if(name!=='fences')assert.equal(k[name],changed[name],name+' unchanged');
 assert.notEqual(authoredGeometry(plan),authoredGeometry(p),'authored fence type invalidates the bake just like height');
 const height=structuredClone(p);height.site.fence.height=7;
 assert.notEqual(authoredGeometry(height),authoredGeometry(p));
 console.log('ok '+type+' bent fence on sloped ground: finite/draped positions, slots, tint, isolated redraw and bake keys');
}
{
 const board=raw('picket').find(p=>p.slot==='boards').geometry,b=bounds(board),p=board.attributes.position;
 near(b.max.x-b.min.x,3.5/12);near(b.max.z-b.min.z,.75/12);near(b.min.y,2/12);near(b.max.y,6);
 const top=Array.from({length:p.count},(_,i)=>i).filter(i=>p.getY(i)>5.999);
 assert.ok(top.length);assert.ok(top.every(i=>Math.abs(p.getX(i)-(b.min.x+b.max.x)/2)<1e-5),'pointed apex narrower than body');
 const posts=raw('picket').filter(p=>p.slot==='posts');assert.ok(posts.some(p=>bounds(p.geometry).max.y>6.2),'capped posts stand above pickets');
 const rails=raw('picket').filter(p=>p.slot==='rails');assert.equal(rails.length,4);assert.ok(rails.every(p=>bounds(p.geometry).max.z>0),'rails behind pickets');
 console.log('ok picket width, thickness, ground gap, pointed top, caps and two rear rails');
}
{
 const all=raw('metal'),rails=all.filter(p=>p.slot==='rails');assert.equal(rails.length,4);
 const low=bounds(rails[0].geometry),high=bounds(rails[1].geometry);near(low.min.y,.25);near(high.max.y,6);
 const pickets=all.filter(p=>p.slot==='boards');
 assert.ok(pickets.every(p=>{const b=bounds(p.geometry);return Math.abs(b.min.y-low.max.y)<1e-5&&Math.abs(b.max.y-high.min.y)<1e-5;}));
 const posts=all.filter(p=>p.slot==='posts'&&p.seed[0]===0);assert.equal(posts.length,4,'13 feet divided into bays no longer than 6 feet');
 near(bounds(posts[1].geometry).min.x-bounds(posts[0].geometry).min.x,13/3);
 console.log('ok metal top/bottom rails, pickets between, evenly spaced posts and 3 inch clearance');
}
{
 const all=raw('panel'),sheets=all.filter(p=>p.slot==='boards');assert.equal(sheets.length,4,'one sheet per <=8 foot bay on both segments');
 for(const {geometry,seed} of sheets){const b=bounds(geometry),uv=geometry.attributes.uv;
  const width=(seed[0]===0?13:Math.hypot(4,9))/2-2.5/12;
  near(Math.max(...Array.from({length:uv.count},(_,i)=>uv.getX(i))),width);
  near(Math.max(...Array.from({length:uv.count},(_,i)=>uv.getY(i))),6-2/12);near(b.min.y,1/12);
 }
 assert.equal(all.filter(p=>p.slot==='rails').length,2,'one top rail per segment');
 for(const id of ['glass','screen','chain_link']){
  const p=structuredClone(plan);p.site.fence={...fence,type:'panel',materials:{boards:{id}}};
  const m=drawn(await buildYard(p,input.kit,'low')).find(o=>o.material.transparent||o.material.alphaTest>0).material;
  assert.equal(m.side,THREE.DoubleSide,id+' panels draw on both sides');
  assert.equal(m.forceSinglePass,true,id+' panels use one submission even with double-sided glass');
 }
 console.log('ok panel sheets per bay, physical-foot UVs, ground clearance and double sided glass/cutout');
}
{
 const p=structuredClone(plan);p.site.fence={...fence,type:'panel',materials:{boards:{id:'panel-glass'}}};
 const entry={kind:'material',household:true,revision:1,maps:{},params:{alpha_mode:'blend',opacity:.4,tint:'#b9d7db'}};
 const kit={...input.kit,manifest:{'panel-glass':entry}},y=await buildYard(p,kit,'low');
 const m=drawn(y).find(o=>o.material.userData.materialId==='panel-glass').material;
 assert.ok([...y.group.userData.materials.values()].includes(m),'panel uses the live cached material, with no pending-texture clone');
 applyMaterialParams(m,{...entry,revision:2,params:{...entry.params,opacity:.3}},m.userData.materialRef,'fence','low');
 assert.equal(m.side,THREE.DoubleSide,'panel sidedness survives in-place Library refresh');near(m.opacity,.3);
 console.log('ok household panel glass shares the live cache and stays double sided after a material refresh');
}
for(const type of types){
 const counts=[];
 for(const length of [10,100]){
  const p={buildings:[],site:{fence:{id:'long',type,height:6,polyline:[[0,0],[length,0]],
   materials:{boards:{id:'red_brick_03'},posts:{id:'mocha_oak_veneer'},rails:{id:'painted_trim'}}}}};
  const batch=drawn(await buildYard(p,input.kit,'low'));counts.push(batch.length);
  assert.ok(batch.every(o=>!Array.isArray(o.material)&&o.geometry.groups.length===0),'one draw per merged mesh');
  assert.equal(batch.length,3,type+' at most one draw per slot material');
  delete p.site.fence.materials;assert.equal(drawn(await buildYard(p,input.kit,'low')).length,1,'shared wood is one draw');
 }
 assert.deepEqual(counts,[3,3]);console.log('ok '+type+' 10/100 ft fence: 3 distinct-slot draws, 1 shared-material draw');
}
for(const type of ['picket','metal','panel'])for(const height of [.1,2,10,50]){
 buildFence({type,height,polyline:[[0,0],[.01,0]]},(g,slot)=>{
  const b=bounds(g);assert.ok([...g.attributes.position.array].every(Number.isFinite));
  if(slot==='boards')assert.ok(b.min.y>=0&&b.max.y<=height+1e-5&&b.max.y>b.min.y,'short legacy heights do not invert infill');
 });
}
console.log('ok short segments and legacy heights keep finite, upright infill for all new types');
{
 const sent=[],piece={...fence,style:'handmade'},host=new Element();let writable=true,pending=Promise.resolve();
 const draw=()=>{host.replaceChildren();drawSiteShapeShelf(host,{kind:'fence',index:0,piece},{
  canEdit:()=>writable,queue:fn=>pending=pending.then(fn),op:async o=>{sent.push(o);Object.assign(piece,o);},report:e=>{throw e;}});};
 draw();const select=host.querySelector('[aria-label="Fence type"]');assert.ok(select);assert.equal(select.value,'plank');
 assert.deepEqual(select.children.map(o=>[o.value,o.textContent]),[['plank','Wood plank'],['picket','Picket'],['metal','Metal picket'],['panel','Panel']]);
 const nodes=host.querySelectorAll('input,select');assert.ok(nodes.indexOf(select)<nodes.indexOf(host.querySelector('[aria-label="Height (ft)"]')));
 for(const type of types){select.value=type;await fire(select,'change');await pending;assert.equal(sent.length,types.indexOf(type)+1);
  assert.deepEqual(sent.at(-1),{op:'update_site_shape',list:'fence',index:0,type});
  const words=siteMaterialSlots('fence',piece).map(r=>r[1]);
  assert.deepEqual(words,[type==='panel'?'Panel':type==='plank'?'Boards':'Pickets','Posts',type==='panel'?'Top rail':'Rails']);
  draw();assert.ok(host.querySelector('[aria-label="Style"]'),'free text style remains');
 }
 writable=false;draw();assert.equal(host.querySelector('[aria-label="Fence type"]').disabled,true);
 await fire(host.querySelector('[aria-label="Fence type"]'),'change');await pending;assert.equal(sent.length,4);
 console.log('ok card select defaults/options/order, one operation per change, type labels, style and read-only');
}
{
 const m=builtinMaterial('chain_link');assert.ok(m.alphaTest>0);assert.equal(m.transparent,false);assert.equal(m.side,THREE.DoubleSide);
 assert.equal(m.userData.alphaMode,'cutout');assert.equal(m.transmission,undefined);assert.equal(m.alphaMap.wrapS,THREE.RepeatWrapping);
 near(m.alphaMap.repeat.x,6);near(m.alphaMap.repeat.y,6);
 const {data,width}=m.alphaMap.image,at=(x,y)=>data[(y*width+x)*4+1];
 assert.equal(at(20,20),255);assert.equal(at(20,108),255);assert.equal(at(32,64),0,'diamond holes');
 console.log('ok generated Chain link: diamond wire mask, 2 inch repeat, alpha test, double sided, no transmission');
}
{
 const m=builtinMaterial('black_metal');assert.equal(m.userData.alphaMode,'opaque');assert.equal(m.transparent,false);assert.equal(m.alphaTest,0);
 assert.equal(m.opacity,1);assert.equal(m.metalness,0);near(m.roughness,.42);assert.equal(m.map,null);assert.equal(m.depthWrite,true);
 const p=structuredClone(plan);p.site.fence={...fence,type:'metal',materials:{boards:{id:'black_metal'},posts:{id:'black_metal'},rails:{id:'black_metal'}}};
 const batch=drawn(await buildYard(p,input.kit,'low'));assert.ok(batch.length>=1&&batch.length<=3);
 for(const o of batch){assert.equal(o.material.color.getHexString(),'1b1c1e');assert.equal(o.material.transparent,false);assert.equal(o.material.userData.alphaMode,'opaque');}
 console.log('ok Black metal: opaque powder-coat look with no maps, drawn on every slot of a metal picket fence');
}
console.log('Fence geometry, batching, keys, card and material checks passed');
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit, 'plankHash': PLANK_HASH})
    print(output)
    sys.exit(code or 0)
