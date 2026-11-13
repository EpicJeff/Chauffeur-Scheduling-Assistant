"""Yard material slots under Node: the real buildYard draws each feature part in the chosen
Library material, and a feature with no slot looks exactly as before.

The user, 2026-11-13: "Why doesn't everything just have a material slot you can assign a
material from the library to?" Porch foundations came first; this covers retaining walls,
fire pits, fences, paths and patios, and planting beds.
"""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
PREFIX = '\n'.join(line for line in PRELUDE.splitlines() if "if (spec === './twin_yard.js')" not in line)
PREFIX = PREFIX.replace("if (spec === 'three')", """if (spec === '@dgreenheck/ez-tree') return {url:data(`import {Group} from '${three}'; export class Tree extends Group {}`),shortCircuit:true};
  if (spec === 'three')""")
DRIVER = PREFIX + r"""
const THREE=await import(three);
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const square=(x0,y0,x1,y1)=>[[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
const BRICK={id:'red_brick_03',color:'#aa3322'}, OAK={id:'mocha_oak_veneer',color:'#336699'};
const hex=m=>'#'+m.color.getHexString();
const meshes=group=>{const out=[];group.traverse(o=>{if(o.isMesh||o.isInstancedMesh)out.push(o);});return out;};
const colours=group=>new Set(meshes(group).flatMap(o=>[].concat(o.material)).filter(m=>m?.color).map(hex));
const signature=group=>meshes(group).map(o=>[[].concat(o.material).map(m=>m.name).join('+'),o.geometry.attributes.position.count]).sort().join('|');
const vertices=group=>meshes(group).reduce((n,o)=>n+o.geometry.attributes.position.count*(o.count||1),0);
// The yard merges by material, so a slot may split a mesh without moving any
// triangle. Compare world-space triangles independently of that batching.
const geometry=group=>{group.updateMatrixWorld(true);return meshes(group).flatMap(o=>{
  const p=o.geometry.attributes.position,ids=o.geometry.index?.array||Array.from({length:p.count},(_,i)=>i),out=[];
  for(let i=0;i<ids.length;i+=3)out.push(JSON.stringify(Array.from(ids.slice(i,i+3),id=>
    new THREE.Vector3().fromBufferAttribute(p,id).applyMatrix4(o.matrixWorld).toArray())));
  return out;
}).sort();};
const appearance=group=>meshes(group).map(o=>[].concat(o.material).map(m=>[m.name,hex(m),m.roughness,m.metalness,m.opacity,m.transparent,m.depthWrite,m.map?.name]));
const site=extra=>({units:'ft',materials:{},buildings:[],site:{terraces:[],...extra}});
let cases=0;
async function pair(label,make,slots,{expect,absent=[],sameShape=true}){
  const plain=await buildYard(site(make({})),input.kit,'low');
  const legacyEmpty=await buildYard(site(make({materials:{}})),input.kit,'low');
  assert.equal(signature(legacyEmpty.group),signature(plain.group),`${label}: an empty slot set is the default look`);
  assert.deepEqual(appearance(legacyEmpty.group),appearance(plain.group),`${label}: default material properties unchanged`);
  const slotted=await buildYard(site(make({materials:slots})),input.kit,'low');
  for(const colour of expect){
    assert.ok(!colours(plain.group).has(colour),`${label}: ${colour} is not in the default look`);
    assert.ok(colours(slotted.group).has(colour),`${label}: the slot draws ${colour}: ${[...colours(slotted.group)]}`);
  }
  for(const colour of absent)assert.ok(!colours(slotted.group).has(colour),`${label}: ${colour} only where chosen`);
  if(sameShape){assert.equal(vertices(slotted.group),vertices(plain.group),`${label}: same geometry, only the material changes`);
    assert.deepEqual(geometry(slotted.group),geometry(plain.group),`${label}: identical positions, indices and transforms`);}
  cases++;return {plain,slotted};
}
// Fence: boards, posts and rails are separate parts.
{
  const fence=extra=>({fence:[{id:'f',polyline:[[0,0],[12,0]],height:6,...extra}]});
  const {slotted}=await pair('fence boards',fence,{boards:BRICK},{expect:['#aa3322']});
  const brick=meshes(slotted.group).filter(o=>hex(o.material)==='#aa3322');
  const wood=meshes(slotted.group).filter(o=>o.material.name==='fence');
  assert.ok(brick.length&&wood.length,'boards are brick while posts and rails stay the default wood');
  await pair('fence posts and rails',fence,{posts:BRICK,rails:OAK},{expect:['#aa3322','#336699']});
}
// Fire pit: body and top, wood and gas.
{
  const wood=extra=>({fire_pit:[{id:'p',at:[0,0],radius:2,fuel:'wood',body:'stone',top:'concrete',...extra}]});
  await pair('wood fire pit',wood,{body:BRICK,top:OAK},{expect:['#aa3322','#336699']});
  const gas=extra=>({fire_pit:[{id:'g',shape:'square',polygon:square(-2,-2,2,2),fuel:'gas',body:'stone',top:'granite',...extra}]});
  const {plain,slotted}=await pair('gas fire pit',gas,{body:BRICK},{expect:['#aa3322'],sameShape:false});
  // The coursed stone veneer is the default body; a chosen body shows its own material instead.
  assert.ok(vertices(slotted.group)<vertices(plain.group),'the default stone veneer steps aside for a chosen body');
}
// Patio and path (surface, curb).
{
  await pair('patio',extra=>({hardscape:[{id:'h',polygon:square(0,0,10,8),material:'paving',...extra}]}),{surface:BRICK},{expect:['#aa3322']});
  await pair('path and curb',extra=>({hardscape:[{id:'w',kind:'path',points:[[0,0],[12,0],[12,9]],width:3,edging:'curb',...extra}]}),
    {surface:BRICK,edging:OAK},{expect:['#aa3322','#336699']});
}
// Planting bed fill.
await pair('bed',extra=>({beds:[{id:'b',polygon:square(0,0,6,4),material:'mulch',...extra}]}),{fill:BRICK},{expect:['#aa3322']});
// Pool coping is a role; walls/floor remain the original untextured plain tile
// unless explicitly slotted. Water never takes either slot.
{
  const pool=extra=>({pool:{id:'pool',polygon:square(0,0,10,6),material:'paving',...extra}});
  const {plain,slotted}=await pair('pool coping',pool,{coping:BRICK},{expect:['#aa3322']});
  const tiles=meshes(plain.group).filter(o=>o.material.name==='pool tile');
  assert.ok(tiles.length,'floor and tile walls are batched together');
  for(const tile of tiles){assert.equal(hex(tile.material),'#5fa8c4');assert.equal(tile.material.roughness,.35);assert.equal(tile.material.map,null);}
  assert.deepEqual(appearance({traverse:fn=>meshes(slotted.group).filter(o=>o.material.name==='pool tile').forEach(fn)}),
    appearance({traverse:fn=>tiles.forEach(fn)}),'coping leaves every tile unchanged');
  const interior=await pair('pool interior',pool,{interior:OAK},{expect:['#336699']});
  const tileVertices=tiles.reduce((n,o)=>n+o.geometry.attributes.position.count,0);
  assert.equal(meshes(interior.slotted.group).filter(o=>hex(o.material)==='#336699').reduce((n,o)=>n+o.geometry.attributes.position.count,0),tileVertices,'all floor and wall tile vertices use interior');
  assert.ok(!meshes(interior.slotted.group).some(o=>o.material.name==='pool tile'),'no tile surface stays unslotted');
  for(const yard of [slotted,interior.slotted]){
    const water=meshes(yard.group).find(o=>o.material.name==='water');
    const original=meshes(plain.group).find(o=>o.material.name==='water');
    assert.deepEqual(appearance({traverse:fn=>fn(water)}),appearance({traverse:fn=>fn(original)}));
  }
}
{
  const edge=extra=>({edges:[{id:'edge',polygon:square(0,0,6,4),...extra}]});
  const {plain,slotted}=await pair('lawn edge strip',edge,{strip:BRICK},{expect:['#aa3322']});
  assert.ok(meshes(plain.group).every(o=>o.material.name==='lawn'),'default strip is the lawn role');
  assert.ok(meshes(slotted.group).every(o=>hex(o.material)==='#aa3322'),'every strip segment takes the slot');
}
// Retaining wall face; the wall kind still sets the default look.
{
  const wall=extra=>({terraces:[{id:'pad',polygon:square(0,0,6,6),height:3,blend:0,
    edges:square(0,0,6,6).map((_,i)=>i?{edge:'sharp'}:{edge:'sharp',wall:{material:'block',thickness_in:8,above_in:6,...extra}})}]});
  const {plain,slotted}=await pair('retaining wall',wall,{face:BRICK},{expect:['#aa3322']});
  assert.ok(meshes(plain.group).some(o=>o.material.name==='retaining_block'),'no slot: the block wall keeps its own role');
  assert.ok(!meshes(slotted.group).some(o=>o.material.name==='retaining_block'),'a face slot replaces the role material');
}
// Two features choosing the same Library material share one material (one draw state).
{
  const cache=new Map();
  const both=await buildYard(site({beds:[{id:'b',polygon:square(0,0,6,4),materials:{fill:BRICK}}],
    hardscape:[{id:'h',polygon:square(20,0,30,8),materials:{surface:BRICK}}]}),input.kit,'low',{materials:cache});
  const bricks=new Set(meshes(both.group).map(o=>o.material).filter(m=>hex(m)==='#aa3322'));
  assert.equal(bricks.size,1,'one shared brick material');
}
console.log(`Passed: ${cases}/${cases} slot scenarios (fence, wood/gas fire pit, patio, path/curb, bed, pool coping/interior, edge strip, retaining wall); defaults unchanged; shared materials`);
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    args = {'root': ROOT.as_posix(), 'kit': kit,
            'manifest': json.loads((ROOT / 'twin_library/manifest.json').read_text(encoding='utf-8'))}
    code, output = run_node(DRIVER, args)
    print(output)
    sys.exit(code or 0)
