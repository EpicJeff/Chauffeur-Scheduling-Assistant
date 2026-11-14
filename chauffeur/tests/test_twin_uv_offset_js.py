"""Per-surface random UV offset (material-library Task 10), through the real generator and yard.

A household material with params.random_offset shifts each surface's base `uv`
by a stable hash of its piece id, inside one tile. Batching keeps one material
instance; the lightmap channels are untouched. Off, the geometry is byte-for-byte
what the generator made before the feature (GOLDEN was taken from 5c58872f).

Run: python tests/test_twin_uv_offset_js.py
"""
import sys
from pathlib import Path
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]
# fingerprint() of every mesh's material name, position and uv in the generator
# and yard fixture below, with random_offset false, computed before this change.
GOLDEN = {'building': '82fcc379d97a2fed6867581730ac1951', 'yard': 'bfb84a281da58500d6dc1ae6addf71dc'}

DRIVER = PREFIX + r"""
globalThis.buildCalls=0;
registerHooks({resolve(spec,ctx,next){
 if(spec==='./twin_generator.js'&&ctx.parentURL.endsWith('/twin_view.js'))return {url:data(`export * from '${file('static/twin/twin_generator.js')}';import {buildTwin as build} from '${file('static/twin/twin_generator.js')}';export function buildTwin(...args){globalThis.buildCalls++;return build(...args);}`),shortCircuit:true};
 return next(spec,ctx);
}});
const THREE=await import('three');
globalThis.__THREE_MESH=THREE.Mesh;globalThis.__THREE_BOX=THREE.BoxGeometry;globalThis.__THREE_STD=THREE.MeshStandardMaterial;
const lib=await import(file('static/twin/twin_library.js'));
const {buildTwin,buildingKey}=await import(file('static/twin/twin_generator.js'));
const {buildYard,yardPartKeys,YARD_PARTS}=await import(file('static/twin/twin_yard.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {fingerprint}=await import(file('static/twin/bake/fingerprint.js'));
const square=(x,y,w=12)=>[[x,y],[x+w,y],[x+w,y+w],[x,y+w]];
const params=(extra={})=>({tint:'#ffffff',roughness:null,metalness:null,normal_scale:1,normal_convention:'gl',ao_intensity:1,tile_ft:[4,4],rotation_deg:0,...extra});
const entry=(extra={},revision=1)=>({kind:'material',household:true,revision,maps:{},params:params(extra)});
const building=(id,x,{roof=true,openings=true}={})=>({id,name:id,position:[x,0],rotation:0,base:0,
 foundation:{mode:'auto',offset_ft:.5,thickness_ft:1},materials:{},
 levels:[{id:'L1',name:'Ground',elevation:0,ceiling:8,outline:square(0,0)}],
 walls:square(0,0).map((from,i,a)=>({id:'w'+i,level:'L1',from,to:a[(i+1)%4],height:8,thickness:.5,exterior:true,state:'settled'})),
 rooms:[{id:'room',level:'L1',name:'Kitchen',polygon:square(0,0),state:'settled'}],
 openings:openings?[{id:'door',wall:'w0',level:'L1',kind:'door',at:3,width:3,sill:0,head:7,state:'settled'}]:[],
 roof:{sections:roof?[{id:'roof',kind:'gable',rect:[0,0,12,12],plate:8,pitch:6,ridge:'x',overhang:1}]:[],flags:[]},
 roofs:[],stairs:[],anchors:[],items:[],fixtures:[],lights:[]});
const ROLES=['floor','patio_concrete','siding','interior_wall','roof','trim','window_frame','door','porch_ceiling','base','lattice','counter','stainless','paving','fence','mulch','lawn','granite','stone'];
// Every role is a household material 'X' except the ones a test keeps plain.
const kitFor=(extra,{plain=[]}={})=>({materials:Object.fromEntries(ROLES.map(r=>[r,plain.includes(r)?{asset:r,color:'#bbccee'}:{id:'X'}])),
 manifest:{X:entry(extra),Y:entry({random_offset:true})}});
const site=()=>({lot:square(-30,-30,90),terraces:[{id:'t1',polygon:square(30,30,8),height:2,blend:3,
  edges:[{edge:'sharp',wall:{material:'stone',thickness_in:8,above_in:1,materials:{face:{id:'X'}}}}]}],
 fence:[{id:'f1',polyline:[[-10,-10],[-2,-10]],height:4,elevation:0,materials:{boards:{id:'X'},posts:{id:'X'},rails:{id:'X'}}}],
 hardscape:[{id:'h1',kind:'patio',polygon:square(-20,0,6),elevation:0,material:'paving',materials:{surface:{id:'X'}}},
  {id:'h2',kind:'patio',polygon:square(-20,10,6),elevation:0,material:'paving',materials:{surface:{id:'X'}}},
  {id:'p1',kind:'path',points:[[20,-10],[28,-10]],width:3,corner:'rounded',smooth:false,radius:1,edging:'curb',elevation:0,material:'paving',materials:{surface:{id:'X'},edging:{id:'X'}}}],
 pool:{id:'pool',polygon:square(15,15,8),depth:4,coping:1,elevation:0,material:'paving',materials:{coping:{id:'X'},interior:{id:'X'}}},
 beds:[{id:'bed1',polygon:square(-20,20,3),elevation:0,material:'mulch',materials:{fill:{id:'X'}}}],
 edges:[{id:'edge1',polygon:square(-10,20,3),elevation:0,material:'lawn',materials:{strip:{id:'X'}}}],
 fire_pit:[{id:'fire',at:[-25,-20],shape:'round',radius:2,rotation:0,fuel:'wood',body:'stone',top:'granite',height_in:18,elevation:0,materials:{body:{id:'X'},top:{id:'X'}}}],
 planting:[],furniture:[]});
const plan=(opts)=>({buildings:[building('a',0,opts)],materials:{},site:site()});
const meshes=root=>{const out=[];root.updateMatrixWorld(true);root.traverse(o=>{if(o.isMesh&&!o.isInstancedMesh)out.push(o);});return out;};
const digest=root=>{const h=fingerprint();for(const m of meshes(root)){h.add([].concat(m.material).map(x=>x.name).join(','));
 for(const n of ['position','uv'])if(m.geometry.attributes[n])h.add(m.geometry.attributes[n].array);}return h.key();};
async function twin(p,k,opts={}){const t=buildTwin(p,k,'low',opts);await t.ready;return t;}
async function yard(p,k){return (await buildYard(p,k,'low',{})).group;}
// Per-vertex uv deltas between two otherwise identical builds, matched to expected offsets.
function deltas(a,b){const out=[];for(let i=0;i<a.length;i+=2)out.push([b[i]-a[i],b[i+1]-a[i+1]]);return out;}
const near=(p,q)=>Math.abs(p[0]-q[0])<2e-3&&Math.abs(p[1]-q[1])<2e-3;
function matched(found,expected){
 const used=new Set();
 for(const d of found){const i=expected.findIndex(e=>near(d,e));assert.ok(i>=0,'unexpected uv delta '+JSON.stringify(d));used.add(i);}
 return used;
}
await test('same_id_same_offset',()=>{
 const a=lib.uvOffsetFor('a:w0',[4,4]),b=lib.uvOffsetFor('a:w0',[4,4]);
 assert.deepEqual(a,b);assert.equal(a.length,2);
 assert.notDeepEqual(lib.uvOffsetFor('a:w1',[4,4]),a);
 for(const id of ['a:w0','a:w1','h1','pool:wall:3','x'.repeat(200),'']){
  const [du,dv]=lib.uvOffsetFor(id,[6,3]);assert.ok(du>=0&&du<6&&dv>=0&&dv<3,id+' in tile');
 }
 // The fraction of the tile is the same for a different tile size: one stable seed.
 const [u4,v4]=lib.uvOffsetFor('a:w2',[4,4]),[u8,v2]=lib.uvOffsetFor('a:w2',[8,2]);
 assert.ok(Math.abs(u4/4-u8/8)<1e-9&&Math.abs(v4/4-v2/2)<1e-9);
 // Spread: 200 ids land in every quarter of the tile.
 const quarters=new Set();for(let i=0;i<200;i++){const [u,v]=lib.uvOffsetFor('w'+i,[4,4]);quarters.add((u>=2)+2*(v>=2));}
 assert.equal(quarters.size,4);
});
await test('off_by_default_geometry_unchanged',async()=>{
 const got={};
 for(const extra of [{random_offset:false},{}]){
  const p=plan(),k=kitFor(extra);
  const b=digest((await twin(p,k)).root),y=digest(await yard(p,k));
  if(process.env.UV_GOLDEN)console.log('    golden',JSON.stringify({building:b,yard:y}));
  assert.equal(b,input.golden.building,'building geometry with '+JSON.stringify(extra));
  assert.equal(y,input.golden.yard,'yard geometry with '+JSON.stringify(extra));
  got[JSON.stringify(extra)]=[b,y];
 }
});
await test('different_walls_different_offsets_same_material_instance',async()=>{
 const p=plan({roof:false,openings:false}),plainRoles=ROLES.filter(r=>r!=='siding');
 const off=await twin(p,kitFor({random_offset:false},{plain:plainRoles})),on=await twin(p,kitFor({random_offset:true},{plain:plainRoles}));
 const siding=t=>meshes(t.root).filter(m=>m.material.name==='siding');
 const a=siding(off),b=siding(on);
 assert.ok(b.length>=1);assert.equal(b.length,a.length,'batching unchanged');
 assert.equal(new Set(b.map(m=>m.material)).size,1,'one material instance');
 assert.ok(b.every(m=>m.userData.merged),'walls still batch');
 const expected=[0,1,2,3].map(i=>lib.uvOffsetFor('a:w'+i,[4,4]));
 const found=b.flatMap((m,i)=>deltas(a[i].geometry.attributes.uv.array,m.geometry.attributes.uv.array));
 assert.equal(matched(found,expected).size,4,'each wall has its own uv origin');
 for(let i=0;i<b.length;i++)assert.deepEqual([...b[i].geometry.attributes.position.array],[...a[i].geometry.attributes.position.array]);
 // Only the base channel moves: no lightmap channel exists or is written here.
 for(const m of b)for(const name of Object.keys(m.geometry.attributes))assert.ok(['position','normal','uv'].includes(name),name);
});
await test('random_offset_reaches_roof_floor_and_yard_surfaces',async()=>{
 const p=plan(),off={b:await twin(p,kitFor({random_offset:false})),y:await yard(p,kitFor({random_offset:false}))};
 const on={b:await twin(p,kitFor({random_offset:true})),y:await yard(p,kitFor({random_offset:true}))};
 const moved=(x,y)=>{const a=meshes(x),b=meshes(y),names=new Set();assert.equal(a.length,b.length);
  a.forEach((m,i)=>{const ua=m.geometry.attributes.uv?.array,ub=b[i].geometry.attributes.uv?.array;
   if(ua&&ub&&ua.some((v,j)=>Math.abs(v-ub[j])>1e-6))names.add(m.material.name);});return names;};
 const house=moved(off.b.root,on.b.root);
 for(const role of ['siding','roof','floor','trim'])assert.ok(house.has(role),'house '+role+' '+[...house]);
 const site=moved(off.y,on.y);
 for(const role of ['paving','fence','mulch','lawn','base','granite','patio_concrete'])assert.ok(site.has(role),'yard '+role+' '+[...site]);
 // Two patios in one material keep one material instance and their own origins.
 const pavingOff=meshes(off.y).filter(m=>m.material.name==='paving'),pavingOn=meshes(on.y).filter(m=>m.material.name==='paving');
 assert.equal(new Set(pavingOn.map(m=>m.material)).size,1);
 const found=pavingOn.flatMap((m,i)=>deltas(pavingOff[i].geometry.attributes.uv.array,m.geometry.attributes.uv.array));
 const ids=['h1','h2','p1','pool:floor','pool:coping',...[0,1,2,3].map(i=>'pool:wall:'+i)];
 const used=matched(found,ids.map(id=>lib.uvOffsetFor(id,[4,4])));
 assert.ok(used.has(0)&&used.has(1),'both patios offset by their own ids');
 // The retaining wall and the fire pit body share 'base'; each keeps its own seed.
 const baseOff=meshes(off.y).filter(m=>m.material.name==='base'),baseOn=meshes(on.y).filter(m=>m.material.name==='base');
 const walls=matched(baseOn.flatMap((m,i)=>deltas(baseOff[i].geometry.attributes.uv.array,m.geometry.attributes.uv.array)),
  ['t1:edge:0','fire:body'].map(id=>lib.uvOffsetFor(id,[4,4])));
 assert.equal(walls.size,2,'retaining wall and fire pit body');
});
await test('building_reuse_and_yard_keys_follow_random_offset_only_when_used',async()=>{
 const p=plan(),k=kitFor({random_offset:false},{plain:ROLES}),K=k=>structuredClone(k);
 p.buildings.push(building('b',40));p.buildings[0].materials.siding={id:'X'};
 const key=(id,kit)=>buildingKey(p,p.buildings.find(b=>b.id===id),kit,'low');
 const toggled=K(k);toggled.manifest.X.params.random_offset=true; // same revision: params alone must count
 assert.notEqual(key('a',toggled),key('a',k),'used material toggled');
 assert.equal(key('b',toggled),key('b',k),'unused material toggled');
 const unrelated=K(k);unrelated.manifest.Y.params.random_offset=false;
 assert.equal(key('a',unrelated),key('a',k));assert.equal(key('b',unrelated),key('b',k));
 const old=await twin(p,k),next=await twin(p,toggled,{previous:old});next.adoptBuildings();
 assert.deepEqual(next.buildingsRebuilt,['a']);assert.deepEqual(next.buildingsReused,['b']);
 // Yard: the hardscape slot uses X; fences use Y. Each part follows only its own material.
 const q=plan();q.site.fence[0].materials={boards:{id:'Y'},posts:{id:'Y'},rails:{id:'Y'}};
 const base=yardPartKeys(q,k,'low'),on=yardPartKeys(q,toggled,'low'),other=yardPartKeys(q,unrelated,'low');
 const changed=keys=>YARD_PARTS.filter(n=>keys[n]!==base[n]);
 assert.ok(changed(on).includes('hardscape'));assert.ok(!changed(on).includes('fences'));assert.ok(!changed(on).includes('plants'));
 assert.deepEqual(changed(other),['fences']);
 const ids=structuredClone(q);ids.site.hardscape[0].id='h9';
 assert.deepEqual(YARD_PARTS.filter(n=>yardPartKeys(ids,k,'low')[n]!==base[n]),['hardscape'],'a piece id seeds its offset');
});
await test('live_toggle_rebuilds_geometry',async()=>{
 const k={materials:{siding:{id:'X'}},manifest:{X:entry({random_offset:false})}};
 const p=plan({openings:false});p.site={lot:square(0,0,6),planting:[]};
 const v=await mountTwin(new Element(),{plan:p,kit:k,tier:'low',bake:false});
 try {
  const uvs=()=>{const out=[];v.scene.traverse(o=>{if(o.isMesh&&o.material?.name==='siding')out.push(...o.geometry.attributes.uv.array);});return out;};
  const before=uvs(),calls=buildCalls;
  k.manifest.X=entry({tint:'#123456'},2);await v.refreshMaterials(['X']);
  assert.equal(buildCalls,calls,'a tint edit stays in place');assert.deepEqual(uvs(),before);
  k.manifest.X=entry({random_offset:true},3);await v.refreshMaterials(['X']);
  assert.equal(buildCalls,calls+1,'turning it on rebuilds the geometry');assert.notDeepEqual(uvs(),before);
  k.manifest.X=entry({random_offset:false},4);await v.refreshMaterials(['X']);
  assert.equal(buildCalls,calls+2,'turning it off rebuilds the geometry');assert.deepEqual(uvs(),before);
 } finally { v.dispose(); }
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'golden': GOLDEN}, timeout=180)
    print(out)
    sys.exit(code or 0)
