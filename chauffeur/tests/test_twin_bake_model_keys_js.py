"""Node CPU proof for plan-only placed-model bake and grid identities."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ground_js import PREFIX, ROOT

DRIVER = PREFIX + r"""
const THREE = await import(three);
const {buildTwin, FT} = await import(file('static/twin/twin_generator.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
const {atlasJob, packAtlas, covered, encodeAtlas} = await import(file('static/twin/bake/atlas_transport.js'));
const {loadAtlas} = await import(file('static/twin/bake/lightmap_material.js'));
const {authoredGeometry} = await import(file('static/twin/bake/geometry_key.js'));
const {placedCopies, occluderHash, MODEL_REACH_MARGIN_M} = await import(file('static/twin/bake/model_occluders.js'));
const {lightKey, gridKey, bakeLayout} = await import(file('static/twin/bake/baker.js'));
const {lightSource} = await import(file('static/twin/bake/reach.js'));
const {ATLAS_VERSION, ATLAS_WORKER_VERSION} = await import(file('static/twin/bake/key_inputs.js'));
const rect=[[0,0],[12,0],[12,12],[0,12]], options={room:{density:1,page:256,gutter:2}};
const plan={buildings:[{id:'house',position:[0,0],base:0,
 levels:[{id:'L1',elevation:0,ceiling:8,outline:rect}],
 walls:[{id:'wall',level:'L1',from:[0,0],to:[12,0],thickness:.5,height:8}],
 rooms:[{id:'room',level:'L1',polygon:rect}],roof:{sections:[]},
 openings:[{id:'door',wall:'wall',at:6,width:3,height:7,sill:0,kind:'door',model:'door-a'}],
 items:[{id:'chair',asset:'chair',host:{floor:'room',u:.5,v:.5},rotation:0}]}],
 site:{furniture:[{id:'table',kind:'table',at:[5,5]}],planting:[
 {id:'tree',preset:'oak',at:[15,15],height:20},
 {id:'import',asset:'import-tree',at:[4,4]}]}};
// A real built receiver scene. The plan fingerprint must work independently of
// model fetches; placed meshes are excluded from atlas receivers at every tier.
const receiverPlan=structuredClone(plan);
receiverPlan.buildings[0].items=[];receiverPlan.buildings[0].openings=[];
const built=buildTwin(receiverPlan,kit,'low',{viewing:true});await built.ready;
built.root.updateMatrixWorld(true);
const atlasFor=p=>buildAtlas(built.root,p,options), origin={x:0,y:0,z:0};
const atMetres=x=>({buildings:[{id:'b',items:[{id:'i',asset:'chair',host:{ground:true,at:[x/FT,0]}}]}]});
const hash=p=>occluderHash(placedCopies(p),origin,6);
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-9,`${a} != ${b}`);
const tests={
 test_moving_an_item_keeps_atlas_key() {
  const baseline=atlasFor(plan).key,worker=atlasJob(built.root,plan,options).cacheKey;
  for(const edit of [p=>p.buildings[0].items[0].rotation=90,
   p=>p.buildings[0].items[0].host.u=.75,p=>p.site.furniture[0].rotation=90,
   p=>p.site.furniture[0].at[0]++,p=>p.site.planting[1].at[0]++,
   p=>p.site.furniture=[],p=>p.site.planting.pop()]) {
   const changed=structuredClone(plan);edit(changed);
   assert.equal(authoredGeometry(changed),authoredGeometry(plan));
   assert.equal(atlasFor(changed).key,baseline);
   assert.equal(atlasJob(built.root,changed,options).cacheKey,worker);
  }
  for(const edit of [p=>p.buildings[0].openings[0].model='door-b',p=>p.site.planting[0].height++]) {
   const changed=structuredClone(plan);edit(changed);
   assert.notEqual(authoredGeometry(changed),authoredGeometry(plan));
   assert.notEqual(atlasFor(changed).key,baseline);
   assert.notEqual(atlasJob(built.root,changed,options).cacheKey,worker);
  }
  const empty={buildings:[],site:{}},onlyImport=structuredClone(empty);
  onlyImport.site.planting=[{id:'i',asset:'import-tree',at:[0,0]}];
  assert.equal(authoredGeometry(empty),authoredGeometry(onlyImport),'adding first imported planting is excluded');
 },
 test_occluder_hash_only_near_lamps() {
  assert.equal(MODEL_REACH_MARGIN_M,5);
  assert.notEqual(hash(atMetres(4)),hash(atMetres(4.5)));
  assert.equal(hash(atMetres(20)),'');assert.equal(hash(atMetres(21)),'');
  assert.notEqual(hash(atMetres(11)),'','inclusive range plus margin');
  assert.equal(hash(atMetres(11.001)),'');
  const copies=placedCopies(atMetres(4));
  assert.equal(occluderHash([...copies,...placedCopies(atMetres(20))],origin,6),hash(atMetres(4)));
  assert.equal(occluderHash([{...copies[0],at:[0,20,0]}],origin,6),'','cull in three dimensions');
 },
 test_casts_shadow_changes_hash() {
  const p=atMetres(4),before=hash(p);p.buildings[0].items[0].casts_shadow=false;
  assert.equal(placedCopies(p)[0].castsShadow,false);assert.notEqual(hash(p),before);
 },
 test_grid_key_ignores_models() {
  const a={key:'atlas'},s={bank:0,channel:0},l={device:'lamp',at:[0,0,0],reach:'receivers',occluders:hash(atMetres(4))};
  const moved={...l,occluders:hash(atMetres(5))};
  assert.notEqual(lightKey(a,l,s),lightKey(a,moved,s));assert.equal(gridKey(a,l,s),gridKey(a,moved,s));
  const lampMoved={...l,at:[1,0,0]};
  assert.notEqual(lightKey(a,l,s),lightKey(a,lampMoved,s));assert.notEqual(gridKey(a,l,s),gridKey(a,lampMoved,s));
  for(const fixture of [{signature:'fixture',kind:1},{signature:'sum',kind:3}]) {
   const slot={assignments:[{chartKey:'chart',bank:0,channel:2}]};
   assert.equal(gridKey(a,{...l,...fixture},slot),gridKey(a,{...moved,...fixture},slot));
   assert.notEqual(lightKey(a,{...l,...fixture},slot),lightKey(a,{...moved,...fixture},slot));
   assert.notEqual(gridKey(a,{...l,...fixture},slot),gridKey(a,{...l,...fixture,signature:'changed'},slot));
  }
 },
 test_versions_bumped() {
  assert.equal(ATLAS_VERSION,'reach-atlas-13');assert.equal(ATLAS_WORKER_VERSION,'atlas-worker-reach-13');
 },
 test_placed_copies_resolve_world_transforms() {
  const p=structuredClone(plan),b=p.buildings[0];
  Object.assign(b,{position:[10,20],rotation:90,foundation:{mode:'auto',offset_ft:1}});
  p.site.terraces=[{polygon:[[-100,-100],[100,-100],[100,100],[-100,100]],height:3,blend:0}];
  b.levels[0].elevation=2;
  Object.assign(b.items[0],{offset:.5,elevation:1,rotation:20,pitch:10,roll:30,scale:2,scale_axes:[2,3,4],mirror_x:true,mirror_y:true});
  const copies=placedCopies(p),item=copies.find(c=>c.id==='item:house:chair');
  assert.equal(copies.length,3,'openings and non-import plants are excluded');
  assert.equal(item.asset,'chair');item.at.forEach((v,i)=>near(v,[4*FT,7.5*FT,-26*FT][i]));
  assert.deepEqual(item.rot,[10,110,30]);assert.deepEqual(item.scale,[-4,6,-8]);assert.equal(item.castsShadow,true);
  const furniture=copies.find(c=>c.id==='furniture:table');
  assert.equal(furniture.asset,'table');assert.deepEqual(furniture.at,[5*FT,3*FT,-5*FT]);
  assert.deepEqual(copies.find(c=>c.id==='planting:import').at,[4*FT,3*FT,-4*FT]);
  // Wall and ceiling hosts use the same resolver as the drawn items.
  b.items=[{id:'wall-item',asset:'chair',host:{wall:'wall',at:3,z:4,side:'left'},offset:.25},
   {id:'ceiling-item',asset:'chair',host:{ceiling:'room',u:.25,v:.5},offset:.5}];
  const hosted=placedCopies(p).filter(c=>c.id.startsWith('item:'));
  hosted[0].at.forEach((v,i)=>near(v,[9.5*FT,10*FT,-23*FT][i]));
  hosted[1].at.forEach((v,i)=>near(v,[4*FT,13.5*FT,-23*FT][i]));
 },
 test_hash_canonical_defaults_and_order() {
  const p=atMetres(4),explicit=structuredClone(p);
  Object.assign(explicit.buildings[0].items[0],{rotation:0,pitch:0,roll:0,scale:1,scale_axes:[1,1,1],mirror_x:false,mirror_y:false,casts_shadow:true,elevation:0,offset:0});
  assert.equal(hash(p),hash(explicit));
  const base=placedCopies(p)[0],other={...base,id:'item:b:other',asset:'table'};
  assert.equal(occluderHash([base,other],origin,6),occluderHash([other,base],origin,6));
  for(const edit of [i=>i.asset='table',i=>i.rotation=1,i=>i.pitch=1,i=>i.roll=1,
   i=>i.scale=2,i=>i.scale_axes=[1,2,1],i=>i.mirror_x=true,i=>i.mirror_y=true]) {
   const changed=structuredClone(p);edit(changed.buildings[0].items[0]);assert.notEqual(hash(changed),hash(p));
  }
  const detail=structuredClone(p);Object.assign(detail.buildings[0].items[0],{lod:2,tint:'#fff',materials:{top:'wood'}});
  assert.equal(hash(detail),hash(p),'render details never enter the hash');
 },
 test_hash_rounds_coordinates_and_angles() {
  const c=placedCopies(atMetres(4)),h=copy=>occluderHash(copy,origin,6),base=h(c);
  assert.equal(h([{...c[0],at:[4.0004,0,0],rot:[.04,0,0]}]),base);
  assert.notEqual(h([{...c[0],at:[4.0006,0,0]}]),base);
  assert.notEqual(h([{...c[0],rot:[.06,0,0]}]),base);
 },
 async test_cached_atlas_uses_current_placements() {
  const a=atlasFor(plan),stored=packAtlas(a,covered(built.root));
  stored.uvKey=atlasJob(built.root,plan,options).uvKey;
  const bytes=await encodeAtlas(stored),changed=structuredClone(plan);
  changed.buildings[0].items[0].host.u=.75;
  const lamp={device:'lamp',building:'house',level:'L1',room:'room',at:[6,6,6]};
  const before=bakeLayout(a,options,[lamp]).entries.lamp;
  for(const apply of [true,false]) {
   const fresh=buildTwin(receiverPlan,kit,'low',{viewing:true});await fresh.ready;fresh.root.updateMatrixWorld(true);
   const loaded=await loadAtlas(fresh.root,changed,options,{apply,indexedDB:null,
    Worker:class {constructor(){throw new Error('A placement edit must reuse the cached atlas');}},
    fetch:async()=>new Response(bytes)});
   const cached=apply?loaded:loaded.apply();
   assert.equal(cached.room.plan,changed,'cache data must use the current plan, including placements');
   const after=bakeLayout(cached,options,[lamp]).entries.lamp;
   assert.notEqual(after.key,before.key);assert.equal(after.grid,before.grid);
  }
 },
 test_bake_layout_uses_occluders_and_keeps_grid() {
  const lamp={device:'lamp',building:'house',level:'L1',room:'room',at:[6,6,6]};
  const a=atlasFor(plan),packed=bakeLayout(a,options,[lamp]);
  const l=packed.lights[0],source=lightSource(plan,l).source;
  assert.ok(packed.entries.lamp);assert.ok(l.occluders);
  assert.equal(l.occluders,occluderHash(placedCopies(plan),source,l.range));
  assert.equal(packed.entries.lamp.grid,gridKey(a,l,packed.slots.lamp,packed.banks[packed.slots.lamp.bank]));
  const changed=structuredClone(plan);changed.buildings[0].items[0].host.u=.75;
  const moved=bakeLayout(atlasFor(changed),options,[lamp]);
  assert.notEqual(moved.entries.lamp.key,packed.entries.lamp.key);assert.equal(moved.entries.lamp.grid,packed.entries.lamp.grid);
  const farLamp={device:'far',absolute:true,at:[1000,1000,6],range:18};
  assert.equal(bakeLayout(a,options,[farLamp]).lights[0].occluders,'');
 }
};
let passed=0;
for(const [name,test] of Object.entries(tests)){await test();console.log(`Passed: ${name}`);passed++;}
console.log(`${passed}/${Object.keys(tests).length} passed`);
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_bake_model_keys_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True,
                                text=True, timeout=120)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
