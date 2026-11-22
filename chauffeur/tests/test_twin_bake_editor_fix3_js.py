"""Round three: cheap idle status, exact pressed runs and conservative migration."""
import sys
import test_twin_bake_runtime_js as R

DRIVER = R.DRIVER[:R.DRIVER.index('await check(')] + r"""
const output=d=>d.host.querySelectorAll('output')[0];
const opts=extra=>({mode:'manual',display:false,poll:0,host:new Node('div'),view:{round:42},...extra});
const ready=d=>until(()=>/^Lighting /.test(output(d)?.textContent),'cheap editor status');
async function seeded(extra={}){const d=await context('high',null,null,opts(extra));await ready(d);assert.equal(d.controller.packing(),null);await d.controller.start();return d;}
await check('legacy_signatures_are_stale_and_press_stamps_without_rendering',async()=>{
 const d=await seeded();let next;
 try{
  const key=d.controller.state().key,m=d.server.manifests.get(key);for(const e of Object.values(m.lights))delete e.cheap;
  next=await context('high',d.server,null,opts());await ready(next);
  assert.equal(next.controller.packing(),null);assert.deepEqual(next.controller.state().stale,['k1','k2','h1','c1']);
  const before=d.server.calls.length;await next.controller.start();
  assert.deepEqual(next.controller.state().baked,[]);assert.equal(next.renderer.log.renders,0);
  assert.equal(output(next).textContent,'Lighting is up to date');
  assert.equal(d.server.writes(before).filter(c=>c.path.endsWith('.png')).length,0);
  assert.equal(d.server.writes(before).filter(c=>c.method==='PUT').length,1,'signatures publish once under the lease');
  for(const e of Object.values(d.server.manifests.get(key).lights))assert.match(e.cheap,/^[a-f0-9]{32}$/);
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('saved_round_change_is_conservative_but_exact_unchanged_keys_cost_no_render',async()=>{
 const d=await seeded();let next;
 try{
  next=await context('high',d.server,null,opts({view:{round:43}}));await ready(next);
  assert.equal(output(next).textContent,'Lighting out of date since your edits');assert.equal(next.controller.state().stale.length,4);
  assert.equal(next.controller.packing(),null);await next.controller.start();
  assert.equal(next.renderer.log.renders,0);assert.deepEqual(next.controller.state().baked,[]);
  assert.equal(output(next).textContent,'Lighting is up to date');assert.equal(d.server.manifests.get(next.controller.state().key).round,43);
  d.server.manifests.get(next.controller.state().key).complete='legacy-truthy';await next.controller.refresh();
  assert.equal(output(next).textContent,'Lighting out of date: 0 lights','complete must be true, not merely truthy');
  await next.controller.start();assert.equal(next.renderer.log.renders,0);assert.equal(output(next).textContent,'Lighting is up to date');
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('ha_move_at_same_round_stales_one_and_press_bakes_exact_key_changes',async()=>{
 const d=await seeded();
 try{
  const key=d.controller.state().key,before=structuredClone(d.server.manifests.get(key));
  const moved=[k1,k2,h1,{...c1,at:[c1.at[0]+1,...c1.at.slice(1)]}];
  d.view.live={layout:()=>liveLayout(moved)};await d.controller.refresh();
  assert.deepEqual(d.controller.state().stale,['c1']);assert.equal(output(d).textContent,'Lighting out of date: 1 lights');
  const since=d.server.calls.length;await d.controller.start();
  const expected=Object.entries(d.controller.packing().entries).filter(([id,e])=>!((e.key===before.lights[id]?.key)&&(e.location===before.lights[id]?.location)&&(e.channel===before.lights[id]?.channel))).map(([id])=>id);
  assert.deepEqual(d.controller.state().baked.slice(4),expected);assert.deepEqual(expected,['c1']);assert.equal(output(d).textContent,'Lighting is up to date');
  assert.ok(d.server.writes(since).length);
 }finally{d.controller.stop();}
});
await check('added_or_removed_ownership_member_stales_all_before_exact_press',async()=>{
 const d=await seeded();
 try{
  const before=structuredClone(d.server.manifests.get(d.controller.state().key));
  const added={...k1,device:'new-member',at:[k1.at[0]+.5,...k1.at.slice(1)]};
  d.view.live={layout:()=>liveLayout([k1,k2,h1,c1,added])};await d.controller.refresh();
  assert.equal(d.controller.state().stale.length,5);const n=d.controller.state().baked.length;await d.controller.start();
  const {matchesEntry}=await import(file('static/twin/bake/freshness.js'));
  const dirty=Object.entries(d.controller.packing().entries).filter(([id,e])=>!matchesEntry(e,before.lights[id])).map(([id])=>id);
  assert.deepEqual([...d.controller.state().baked.slice(n)].sort(),dirty.sort());assert.equal(d.controller.state().stale.length,0);
  d.view.live={layout:()=>liveLayout([k1,k2,h1,c1])};await d.controller.refresh();assert.equal(d.controller.state().stale.length,4);
 }finally{d.controller.stop();}
});
await check('damage_uses_metadata_only_and_plain_press_repairs_affected_channels',async()=>{
 const d=await seeded();let next;
 try{
  const key=d.controller.state().key,m=d.server.manifests.get(key),p=m.lights.k1.pages[0];
  d.server.pages.set(key+'/'+p,new Uint8Array([0,1,2]));m.damageRevision=1;
  const since=d.server.calls.length;next=await context('high',d.server,null,opts());await until(()=>!!next.controller.state().error,'stat damage reported');
  assert.ok(next.controller.state().stale.includes('k1'));assert.equal(next.controller.packing(),null);
  assert.ok(d.server.calls.slice(since).filter(c=>c.path.endsWith('.png')).every(c=>c.inm==='*'&&!c.full));
  const affected=Object.entries(m.lights).filter(([,e])=>e.pages.includes(p)).map(([id])=>id);
  await next.controller.start();assert.deepEqual([...next.controller.state().baked].sort(),affected.sort());assert.equal(next.controller.fresh().length,4);
  d.server.pages.set(key+'/'+p,new Uint8Array([0,1,2]));d.server.manifests.get(key).damageRevision=2;
  await next.controller.refresh();assert.match(next.controller.state().error,/damaged stored page/);
  // Another desk publishes a new rendered page/receipt before this desk presses.
  const fill=FILL.value;FILL.value=.24;
  try{await d.controller.now();}finally{FILL.value=fill;}
  const renders=next.renderer.log.renders,n=next.controller.state().baked.length;
  await next.controller.start();assert.equal(next.renderer.log.renders,renders);assert.deepEqual(next.controller.state().baked.slice(n),[]);
  assert.equal(next.controller.fresh().length,4,'a newer repair supersedes the chip\'s old damage report');
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('legacy_page_migration_and_wrong_dimensions_wait_for_a_press',async()=>{
 const d=await seeded();let next;
 try{
  const key=d.controller.state().key,m=d.server.manifests.get(key);delete m.pageIntegrity;for(const e of Object.values(m.lights))delete e.cheap;
  const since=d.server.calls.length;next=await context('high',d.server,null,opts());await ready(next);
  assert.equal(next.controller.state().stale.length,4);assert.equal(d.server.calls.slice(since).filter(c=>c.path.endsWith('.png')).length,0);
  await next.controller.start();assert.equal(next.renderer.log.renders,0);assert.equal(next.controller.fresh().length,4);
  next.controller.stop();const legacy=d.server.manifests.get(key),p=legacy.lights.k1.pages[0];delete legacy.pageIntegrity;
  d.server.pages.set(key+'/'+p,await B.encodePage(E,{width:4,height:4,channels:[new Uint8Array(16),new Uint8Array(16)]}));
  next=await context('high',d.server,null,opts());await ready(next);assert.equal(next.renderer.log.renders,0);
  await next.controller.start();assert.ok(next.controller.state().baked.includes('k1'));assert.equal(next.controller.fresh().length,4);
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('pressed_exact_key_wins_over_another_desks_newer_old_round_publication',async()=>{
 const d=await seeded();let next;
 try{
  const key=d.controller.state().key,m=structuredClone(d.server.manifests.get(key));m.round=41;
  d.server.manifests.set('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',m);
  next=await context('high',d.server,null,opts());await ready(next);
  assert.equal(output(next).textContent,'Lighting out of date since your edits');
  await next.controller.start();assert.equal(next.controller.state().key,key);
  assert.deepEqual(next.controller.state().baked,[]);assert.equal(next.renderer.log.renders,0);
  assert.equal(output(next).textContent,'Lighting is up to date');
  await next.controller.refresh();assert.equal(output(next).textContent,'Lighting is up to date');
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('committed_wall_finish_press_rebakes_only_real_changes_and_preserves_remote_pages',async()=>{
 const plan=structuredClone(job.plan),remote={device:'remote',building:'far',level:'L1',room:'far-lamp',at:[1005,5,6]},list=[k1,k2,h1,c1,remote];
 const d=await context('high',null,list,opts({plan,farSurface:true,farLamp:true,view:{round:42}}));let next;
 try{
  await ready(d);await d.controller.start();const key=d.controller.state().key,before=structuredClone(d.server.manifests.get(key)),bytes=new Map(d.server.pages);
  const edited=structuredClone(plan);edited.buildings[0].walls[0].faces={left:{color:'#224466'},right:{color:'#224466'}};
  d.controller.stop();next=await context('high',d.server,list,opts({plan:edited,farSurface:true,farLamp:true,view:{round:43}}));await ready(next);
  assert.equal(output(next).textContent,'Lighting out of date since your edits');assert.equal(next.controller.state().stale.length,list.length);assert.equal(next.controller.packing(),null);
  const since=d.server.calls.length;await next.controller.start();assert.equal(next.controller.state().key,key);
  const {matchesEntry}=await import(file('static/twin/bake/freshness.js'));
  const entries=next.controller.packing().entries,dirty=Object.entries(entries).filter(([id,e])=>!matchesEntry(e,before.lights[id])).map(([id])=>id);
  assert.ok(dirty.length>0&&dirty.length<list.length);assert.ok(!dirty.includes('remote'));
  assert.deepEqual([...next.controller.state().baked].sort(),dirty.sort());assert.equal(output(next).textContent,'Lighting is up to date');
  const changed=new Set(dirty.flatMap(id=>entries[id].pages)),untouched=before.lights.remote.pages.filter(p=>!changed.has(p));assert.ok(untouched.length);
  for(const p of untouched){assert.deepEqual(d.server.pages.get(key+'/'+p),bytes.get(key+'/'+p));assert.ok(!d.server.writes(since).some(c=>c.path===`api/house/bakes/${key}/${p}.png`));}
 }finally{next?.controller.stop();d.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())
