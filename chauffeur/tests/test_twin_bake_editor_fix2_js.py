"""Round two: identical physical freshness and bounded page inspection."""
import sys
import test_twin_bake_runtime_js as R
DRIVER = R.DRIVER[:R.DRIVER.index('await check(')] + r"""
const output=d=>d.host.querySelectorAll('output')[0];
const opts=extra=>({mode:'manual',display:false,poll:0,host:new Node('div'),...extra});
const ready=d=>until(()=>d.controller.state().key && d.controller.packing() && /^(Lighting |Could not read baked lighting)/.test(output(d)?.textContent),'physical inspection ready');
async function seeded(){const d=await context('high',null,null,opts());await ready(d);await d.controller.start();return d;}
async function pair(seed,placed,extra={}){
 const editor=await context('high',seed.server,placed,opts(extra));
 const viewer=await context('high',seed.server,placed,{...extra,view:{...extra.view},mode:'readonly',parent:true,poll:0,host:new Node('div')});
 await ready(editor);await until(()=>!!viewer.controller.packing(),'viewer ready');await viewer.controller.refresh();
 assert.deepEqual(editor.controller.state().stale,viewer.controller.state().stale);
 assert.deepEqual(editor.controller.packing().entries,viewer.controller.packing().entries);
 return [editor,viewer];
}
await check('1_legacy_complete_round_cannot_hide_moved_light_or_material_reach',async()=>{
 const seed=await seeded(),key=seed.controller.state().key,m=seed.server.manifests.get(key);
 m.round=42;m.complete=true;delete m.pageIntegrity;for(const e of Object.values(m.lights))delete e.input;
 const moved=[{...k1,at:[k1.at[0]+1,...k1.at.slice(1)]},k2,h1,c1];
 let desks=[];
 try{
  desks=await pair(seed,moved,{view:{round:42}});assert.ok(desks[0].controller.state().stale.includes('k1'));
  for(const d of desks)d.controller.stop();desks=[];
  const d=await context('high',seed.server,null,opts({materialRole:'interior_wall',view:{round:42}}));desks=[d];
  await ready(d);assert.ok(d.controller.state().stale.length,'changed authored reach invalidates the old complete round');
  await d.controller.start();const before=d.server.calls.length;
  const {applyMaterialParams}=await import(file('static/twin/twin_library.js'));
  const entry={household:true,revision:2,params:{tint:'#998877'},maps:{}};
  for(const material of d.out.materials.values())if(material.userData.materialId==='material-baked')
    applyMaterialParams(material,entry,{id:'material-baked'},'interior_wall','high');
  d.view.materialManifest={'material-baked':entry};assert.equal(d.controller.materialsChanged(['material-baked']),true);
  assert.match(output(d).textContent,/^Checking baked lighting/,'known changed inputs never keep claiming up to date during the idle wait');
  await until(()=>d.controller.state().stale.length>0,'in-place Library changes refresh physical keys after idle');
  const previous=JSON.stringify(d.controller.packing().entries);
  entry.revision=3;entry.params.tint='#223344';
  for(const material of d.out.materials.values())if(material.userData.materialId==='material-baked')
    applyMaterialParams(material,entry,{id:'material-baked'},'interior_wall','high');
  d.controller.materialsChanged();
  await until(()=>JSON.stringify(d.controller.packing().entries)!==previous,'whole-library notifications also invalidate cached reach');
  assert.equal(d.server.writes(before).length,0,'a material notification never starts a bake');
 }finally{for(const d of desks)d.controller.stop();seed.controller.stop();}
});
await check('2_unreached_material_colour_does_not_invalidate_or_stamp_receipts',async()=>{
 const plan=structuredClone(job.plan),far=structuredClone(plan.buildings[0]);far.id='far-colour';far.position=[1000,1000];plan.buildings.push(far);
 const seed=await context('high',null,null,opts({plan}));await ready(seed);await seed.controller.start();let desks=[];
 try{
  const next=structuredClone(plan);next.buildings.at(-1).materials={...(far.materials||{}),interior_wall:{color:'#335577'}};
  desks=await pair(seed,null,{plan:next});assert.deepEqual(desks[0].controller.state().stale,[]);
  const before=seed.server.calls.length;await desks[0].controller.start();assert.equal(seed.server.writes(before).length,0,'colour on an unreached wall causes no receipt-only publication');
 }finally{for(const d of desks)d.controller.stop();seed.controller.stop();}
});
await check('2_ownership_reset_and_colour_only_changes_match_the_viewer',async()=>{
 const seed=await seeded(),key=seed.controller.state().key,m=seed.server.manifests.get(key);let desks=[];
 try{
  const colours=[{...k1,color:[.2,.5,.8]},k2,h1,c1];desks=await pair(seed,colours);
  assert.deepEqual(desks[0].controller.state().stale,[],'live colour is not baked');
  const before=seed.server.calls.length;await desks[0].controller.start();
  assert.equal(seed.server.writes(before).length,0,'no receipt-only stamping lease/write');
  for(const d of desks)d.controller.stop();desks=[];
  m.ownership={broken:true};desks=await pair(seed,colours);
  assert.equal(desks[0].controller.state().stale.length,4,'damaged ownership invalidates every light');
 }finally{for(const d of desks)d.controller.stop();seed.controller.stop();}
});
await check('3_unchanged_manifest_skips_pages_and_damage_has_the_same_repair_action',async()=>{
 const seed=await seeded(),key=seed.controller.state().key,m=seed.server.manifests.get(key);let desks=[];
 try{
  const before=seed.server.calls.length;await seed.controller.refresh();await seed.controller.refresh();
  assert.equal(seed.server.calls.slice(before).filter(c=>/\.png$/.test(c.path)).length,0,'idle polls never fetch page bytes or stat checks');
  desks=await pair(seed);
  const p=m.lights.k1.pages[0],id=key+'/'+p;
  seed.server.pages.set(id,new Uint8Array([0,1,2]));m.damageRevision=1;
  for(const d of desks)await d.controller.refresh();
  assert.deepEqual(desks[0].controller.state().stale,desks[1].controller.state().stale);
  assert.ok(desks[0].controller.state().stale.includes('k1'),'even a 304 must carry matching page integrity');
  for(const d of desks)assert.match(d.controller.state().error,/damaged stored page/);
  assert.equal(desks[0].host.querySelectorAll('button').find(b=>b.textContent==='Re-bake all lighting').hidden,false);
  await desks[0].controller.now();assert.equal(desks[0].controller.fresh().length,4,'force repairs damaged bytes');
  const legacy=seed.server.manifests.get(key);delete legacy.pageIntegrity;
  seed.server.pages.set(id,await B.encodePage(E,{width:4,height:4,channels:[new Uint8Array(16),new Uint8Array(16)]}));
  for(const d of desks)await d.controller.refresh();
  assert.deepEqual(desks[0].controller.state().stale,desks[1].controller.state().stale);
  for(const d of desks)assert.match(d.controller.state().error,/Lightmap page/,'legacy bytes are decoded rather than trusted as present');
  await desks[0].controller.now();await desks[1].controller.refresh();
  for(const d of desks)assert.equal(d.controller.fresh().length,4);
 }finally{for(const d of desks)d.controller.stop();seed.controller.stop();}
});
await check('6_spend_visibility_equals_generation_bar_including_directing',async()=>{
 const {createStatusChip}=await import(file('static/twin/editor/status_chip.js'));
 const host=new Node('div'),chip=createStatusChip(host);
 for(const state of [null,'running','paused','checkpoint','stopped','done','failed'])for(const directing of [false,true]){
  chip.update({state,directing,cost:3,estimate:5});
  const visible=directing||['running','paused','stopped','checkpoint'].includes(state);
  assert.equal(host.children[1].hidden,!visible);assert.equal(host.children[2].hidden,!visible);
 }
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())
