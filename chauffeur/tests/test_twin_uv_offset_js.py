"""Per-surface random UV offset (material-library Task 10), through the real generator and yard.

A household material with params.random_offset shifts each surface's base `uv`
by a stable hash of its piece id (a fixed 0..64 ft range; vertical faces u only). Batching keeps one material
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
# Both were captured again when the house slab moved to just under the floor finish
# and the retaining wall face moved proud of the pad edge.
GOLDEN = {'building': '82c28968e3bff83ab3108f06e4ac5caa', 'yard': 'c9eac660122601e038e7f37e88920b1c'}

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
const {fingerprint}=await import(file('static/twin/bake/geometry_key.js'));
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
// Per-vertex [du, dv, |normal.y|] between two otherwise identical builds.
function deltas(a,b){const ua=a.geometry.attributes.uv.array,ub=b.geometry.attributes.uv.array,n=b.geometry.attributes.normal,out=[];
 for(let i=0;i<ua.length/2;i++)out.push([ub[2*i]-ua[2*i],ub[2*i+1]-ua[2*i+1],n?Math.abs(n.getY(i)):1]);return out;}
// Vertical faces move along u only; everything else on both axes.
const expect=(id,ny)=>{const [du,dv]=lib.uvOffsetFor(id);return [du,ny<.5?0:dv];};
const near=(p,q)=>Math.abs(p[0]-q[0])<2e-3&&Math.abs(p[1]-q[1])<2e-3;
const pairs=(x,y,name)=>{const a=meshes(x).filter(m=>m.material.name===name),b=meshes(y).filter(m=>m.material.name===name);
 assert.equal(b.length,a.length,name+' batching unchanged');return a.map((m,i)=>[m,b[i]]);};
// The seeds that explain every vertex's delta; any unexplained delta fails.
function seedsOf(list,ids){const used=new Set();
 for(const [a,b] of list)for(const d of deltas(a,b)){const id=ids.find(id=>near(d,expect(id,d[2])));assert.ok(id,'unexpected uv delta '+JSON.stringify(d));used.add(id);}
 return used;}
await test('same_id_same_offset',()=>{
 const a=lib.uvOffsetFor('a:w0'),b=lib.uvOffsetFor('a:w0');
 assert.deepEqual(a,b);assert.equal(a.length,2);
 assert.notDeepEqual(lib.uvOffsetFor('a:w1'),a);
 for(const id of ['a:w0','a:w1','h1','pool:walls','x'.repeat(200),'']){
  const [du,dv]=lib.uvOffsetFor(id);assert.ok(du>=0&&du<64&&dv>=0&&dv<64,id+' in the fixed 64 ft range');
 }
 assert.equal(lib.UV_OFFSET_RANGE_FT,64);
 // Spread: 200 ids land in every quarter of the range.
 const quarters=new Set();for(let i=0;i<200;i++){const [u,v]=lib.uvOffsetFor('w'+i);quarters.add((u>=32)+2*(v>=32));}
 assert.equal(quarters.size,4);
});
await test('off_by_default_geometry_unchanged',async()=>{
 for(const extra of [{random_offset:false},{}]){
  const p=plan(),k=kitFor(extra);
  const b=digest((await twin(p,k)).root),y=digest(await yard(p,k));
  if(process.env.UV_GOLDEN)console.log('    golden',JSON.stringify({building:b,yard:y}));
  assert.equal(b,input.golden.building,'building geometry with '+JSON.stringify(extra));
  assert.equal(y,input.golden.yard,'yard geometry with '+JSON.stringify(extra));
 }
});
await test('different_walls_different_offsets_same_material_instance',async()=>{
 const p=plan({roof:false,openings:false}),plainRoles=ROLES.filter(r=>r!=='siding');
 const off=await twin(p,kitFor({random_offset:false},{plain:plainRoles})),on=await twin(p,kitFor({random_offset:true},{plain:plainRoles}));
 const list=pairs(off.root,on.root,'siding'),b=list.map(([,m])=>m);
 assert.ok(b.length>=1);
 assert.equal(new Set(b.map(m=>m.material)).size,1,'one material instance');
 assert.ok(b.every(m=>m.userData.merged),'walls still batch');
 assert.equal(seedsOf(list,[0,1,2,3].map(i=>'a:w'+i)).size,4,'each wall has its own uv origin');
 for(const [a,m] of list)assert.deepEqual([...m.geometry.attributes.position.array],[...a.geometry.attributes.position.array]);
 // Only the base channel moves: no lightmap channel exists or is written here.
 for(const m of b)for(const name of Object.keys(m.geometry.attributes))assert.ok(['position','normal','uv'].includes(name),name);
});
await test('brick_wall_pair_at_a_corner_keeps_v',async()=>{
 const p=plan({roof:false,openings:false}),plainRoles=ROLES.filter(r=>r!=='siding');
 const off=await twin(p,kitFor({random_offset:false},{plain:plainRoles})),on=await twin(p,kitFor({random_offset:true},{plain:plainRoles}));
 let vertical=0;
 for(const [a,b] of pairs(off.root,on.root,'siding'))for(const [du,dv,ny] of deltas(a,b))if(ny<.5){vertical++;assert.ok(Math.abs(dv)<1e-4,'courses stay registered: dv '+dv);}
 assert.ok(vertical>0);
 // w0 and w1 meet at a corner: their u origins differ, their v is untouched.
 assert.notEqual(lib.uvOffsetFor('a:w0')[0],lib.uvOffsetFor('a:w1')[0]);
});
await test('floors_share_one_origin_per_level',async()=>{
 const p=plan({roof:false,openings:false}),b=p.buildings[0];
 b.rooms=[{id:'r1',level:'L1',name:'Kitchen',polygon:[[0,0],[6,0],[6,12],[0,12]],state:'settled'},
  {id:'r2',level:'L1',name:'Dining',polygon:[[6,0],[12,0],[12,12],[6,12]],state:'settled'}];
 const plainRoles=ROLES.filter(r=>r!=='floor');
 const off=await twin(p,kitFor({random_offset:false},{plain:plainRoles})),on=await twin(p,kitFor({random_offset:true},{plain:plainRoles}));
 assert.deepEqual([...seedsOf(pairs(off.root,on.root,'floor'),['a:floor:L1','a:r1','a:r2'])],['a:floor:L1'],'two rooms, one level origin');
 assert.ok(on.pieces.has('a:r1')&&on.pieces.has('a:r2'),'each room is still its own piece');
});
await test('tile_ft_edit_never_moves_uv',async()=>{
 const p=plan(),k4=kitFor({random_offset:true}),k6=kitFor({random_offset:true,tile_ft:[6,3]});
 assert.equal(digest((await twin(p,k6)).root),digest((await twin(p,k4)).root));
 assert.equal(digest(await yard(p,k6)),digest(await yard(p,k4)));
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
 // Two patios in one material keep one material instance and their own origins; the
 // pool's walls share one origin.
 const paving=pairs(off.y,on.y,'paving');
 assert.equal(new Set(paving.map(([,m])=>m.material)).size,1);
 const used=seedsOf(paving,['h1','h2','p1','pool:floor','pool:coping','pool:walls']);
 assert.ok(used.has('h1')&&used.has('h2')&&used.has('pool:walls'),[...used].join());
 // The retaining wall and the fire pit body share 'base'; each keeps its own seed.
 assert.deepEqual([...seedsOf(pairs(off.y,on.y,'base'),['t1:walls','fire:body'])].sort(),['fire:body','t1:walls']);
 // A curbed path: one origin per side, continuous along every segment of that side.
 assert.deepEqual([...seedsOf(pairs(off.y,on.y,'patio_concrete'),['p1:curb:left','p1:curb:right'])].sort(),['p1:curb:left','p1:curb:right']);
});
await test('retaining_walls_share_one_origin_per_terrace',async()=>{
 const p={buildings:[],materials:{},site:{lot:square(-10,-10,40),planting:[],furniture:[],terraces:[{id:'t9',polygon:square(0,0,10),height:3,blend:3,
  edges:[0,1,2,3].map(i=>i<2?{edge:'sharp',wall:{material:'stone',thickness_in:8,above_in:6,materials:{face:{id:'X'}}}}:{edge:'slope'})}]}};
 const off=await yard(p,kitFor({random_offset:false})),on=await yard(p,kitFor({random_offset:true}));
 const list=pairs(off,on,'base');
 assert.deepEqual([...seedsOf(list,['t9:walls','t9:edge:0','t9:edge:1'])],['t9:walls'],'both edges, one origin');
 let vertical=0;for(const [a,b] of list)for(const [,dv,ny] of deltas(a,b))if(ny<.5){vertical++;assert.ok(Math.abs(dv)<1e-4);}
 assert.ok(vertical>0,'the corner keeps its courses');
});
await test('bake_layout_ignores_random_offset',async()=>{
 const {buildAtlas}=await import(file('static/twin/bake/atlas.js'));
 const {atlasJob}=await import(file('static/twin/bake/atlas_transport.js'));
 const options={room:{density:1,page:256,gutter:2}},p=plan();
 const scene=async on=>{const k=kitFor({random_offset:on}),house=buildTwin(p,k,'low',{viewing:true});await house.ready;
  house.root.add((await buildYard(p,k,'low',{viewing:true})).group);house.root.updateMatrixWorld(true);return house.root;};
 const off=await scene(false),on=await scene(true);
 const jobOff=atlasJob(off,p,options),jobOn=atlasJob(on,p,options);
 assert.notEqual(jobOn.uvKey,jobOff.uvKey,'the cached geometry knows its base uv');
 assert.notEqual(jobOn.cacheKey,jobOff.cacheKey,'and the input cache keeps them apart');
 const a=buildAtlas(await scene(false),p,options),b=buildAtlas(await scene(true),p,options);
 assert.equal(b.key,a.key,'toggling random_offset leaves the bake layout fresh');
 assert.deepEqual(b.room.charts.map(c=>c.key),a.room.charts.map(c=>c.key),'and every chart key');
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
  k.manifest.X=entry({random_offset:true},5);await v.refreshMaterials(['X']);const shifted=uvs();
  k.manifest.X=entry({random_offset:true,tile_ft:[6,3]},6);await v.refreshMaterials(['X']);
  assert.equal(buildCalls,calls+3,'a tile edit stays in place');assert.deepEqual(uvs(),shifted,'and never moves uv');
 } finally { v.dispose(); }
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'golden': GOLDEN}, timeout=180)
    print(out)
    sys.exit(code or 0)
