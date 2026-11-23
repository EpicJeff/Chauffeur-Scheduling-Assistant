"""Round four: cheap key inputs and intentionally real-time publications."""
import sys
import test_twin_bake_runtime_js as R

DRIVER = R.DRIVER[:R.DRIVER.index('await check(')] + r"""
const {lightSource}=await import(file('static/twin/bake/reach.js'));
const {ATLAS_VERSION}=await import(file('static/twin/bake/key_inputs.js'));
const output=d=>d.host.querySelectorAll('output')[0];
const opts=extra=>({mode:'manual',display:false,poll:0,parent:true,host:new Node('div'),view:{round:42},...extra});
const ready=d=>until(()=>/^Lighting /.test(output(d)?.textContent),'cheap editor status');
async function seed(){const d=await context('high',null,null,opts());await ready(d);await d.controller.start();return d;}
for(const change of ['atlas version','generator version','material alpha','material reach','stage']){
 await check('cheap_inputs_'+change.replaceAll(' ','_')+'_stale_editor_chip_viewer_stays_exact',async()=>{
  const d=await seed();let editor,viewer;
  try{
   const key=d.controller.state().key,m=d.server.manifests.get(key),v={round:42};
   assert.ok(m.keyInputs);assert.match(output(d).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);
   if(change==='atlas version')m.keyInputs.atlas='reach-atlas-11';
   if(change==='generator version')m.keyInputs.generator='before-drip-line';
   if(change==='material alpha')v.materialManifest={library:{revision:1,params:{alpha_mode:'cutout'}}};
   if(change==='material reach')v.materialManifest={library:{revision:2,params:{tint:'#112233'}}};
   if(change==='stage')v.stage={centre:[0,0],radius:400};
   const since=d.server.calls.length;
   editor=await context('high',d.server,null,opts({view:{...v}}));await ready(editor);
   assert.equal(output(editor).textContent,'Lighting out of date: 4 lights');
   assert.equal(editor.controller.packing(),null);assert.equal(editor.renderer.log.renders,0);
   assert.ok(d.server.calls.slice(since).filter(c=>c.path.endsWith('.png')).every(c=>c.inm==='*'&&!c.full));
   // The viewer decides exactly from the entries at its own key. A stamp-only
   // difference (same key, same entries) must keep every baked channel.
   viewer=await context('high',d.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{...v}});
   await until(()=>!!viewer.controller.packing(),'viewer layout');await viewer.controller.refresh();
   assert.equal(viewer.controller.state().stale.length,0);assert.equal(viewer.controller.fresh().length,4);
   assert.ok(!viewer.host.textContent.includes('Lighting is out of date'));
   // A press validates the exact key even when only conservative stamps differ.
   const renders=editor.renderer.log.renders;await editor.controller.start();
   assert.equal(editor.renderer.log.renders,renders);assert.equal(output(editor).textContent,'Lighting is up to date');
  }finally{editor?.controller.stop();viewer?.controller.stop();d.controller.stop();}
 });
}
await check('site_change_leaves_both_desks_current',async()=>{
 const d=await seed();let editor,viewer;
 try{
  const v={round:42,site:{lat:1,lon:2,tz:'UTC',bearing:90,revision:2}};
  editor=await context('high',d.server,null,opts({view:{...v}}));await ready(editor);
  assert.equal(output(editor).textContent,'Lighting is up to date');
  viewer=await context('high',d.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{...v}});
  await until(()=>!!viewer.controller.packing(),'viewer layout');await viewer.controller.refresh();
  assert.equal(viewer.controller.state().stale.length,0);assert.equal(viewer.controller.fresh().length,4);
 }finally{editor?.controller.stop();viewer?.controller.stop();d.controller.stop();}
});
await check('addon_key_change_stales_both_desks_until_a_real_rebake',async()=>{
 const d=await seed();let editor,viewer;
 try{
  // The previous add-on published under another exact key with its own stamp.
  const key=d.controller.state().key,old=d.server.manifests.get(key);d.server.manifests.delete(key);
  old.keyInputs.atlas='reach-atlas-11';d.server.manifests.set('a'.repeat(32),old);
  editor=await context('high',d.server,null,opts());await ready(editor);
  assert.equal(output(editor).textContent,'Lighting out of date: 4 lights');
  // No manifest at the viewer's own key: it builds no layout and keeps every light real-time.
  viewer=await context('high',d.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{round:42}});
  await until(()=>/Lighting is out of date/.test(viewer.host.textContent),'viewer reads the missing key');
  assert.equal(viewer.controller.state().stale.length,4);assert.equal(viewer.controller.fresh().length,0);
  const renders=editor.renderer.log.renders;await editor.controller.start();
  assert.ok(editor.renderer.log.renders>renders,'a real key change rebakes');
  assert.match(output(editor).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);
  await viewer.controller.refresh();
  await until(()=>viewer.controller.state().stale.length===0&&viewer.controller.fresh().length===4,'viewer adopts the rebake');
 }finally{editor?.controller.stop();viewer?.controller.stop();d.controller.stop();}
});
function oneChart(d){
 d.out.root.clear();
 const m=new THREE.Mesh(new THREE.PlaneGeometry(.4,.4).rotateX(-Math.PI/2),new THREE.MeshStandardMaterial({name:'floor'}));
 const source=lightSource(job.plan,k1).source;
 m.userData={merged:true,buildingId:job.pool};m.position.set(source.x/gen.FT,source.y/gen.FT-1,-k1.at[1]);d.out.root.add(m);
}
await check('partial_publication_does_not_sign_unfinished_entries_under_new_global_inputs',async()=>{
 const d=await seed();let editor,viewer;
 try{
  const key=d.controller.state().key,m=d.server.manifests.get(key);
  m.keyInputs.atlas='previous-addon';m.lights.k1.key='0'.repeat(32);m.lights.c1.key='0'.repeat(32);
  const out=gen.buildTwin(job.plan,job.kit,'high');await out.ready;
  const atlas=buildAtlas(out.root,job.plan,job.layout);assert.equal(atlas.key,key);
  const baker=B.createBaker(d.view,{renderer:d.renderer,atlas,layout:job.layout,lights:[k1,k2,h1,c1],api:d.server.api,
    codec:{encode:async j=>B.encodePage(E,j),decode:async bytes=>B.decodePage(T,bytes)}});
  assert.equal(await baker.bakeNext(),'k1');
  const published=d.server.manifests.get(key);assert.equal(published.keyInputs.atlas,ATLAS_VERSION);
  assert.equal(published.lights.c1,undefined,'unfinished exact entries are excluded from a partial publication');assert.equal(published.complete,false);
  editor=await context('high',d.server,null,opts());await ready(editor);assert.deepEqual(editor.controller.state().stale,['c1']);
  viewer=await context('high',d.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{round:42}});
  await until(()=>!!viewer.controller.packing(),'viewer layout');await viewer.controller.refresh();assert.deepEqual(viewer.controller.state().stale,['c1']);
 }finally{editor?.controller.stop();viewer?.controller.stop();d.controller.stop();}
});
await check('fallback_and_no_reach_settle_current_without_claiming_baked_slots',async()=>{
 const list=Array.from({length:7},(_,i)=>({...k1,device:'dense-'+i,at:[k1.at[0]+i*.02,k1.at[1],k1.at[2]+i*.02]}));
 list.push({...k1,device:'unreached',at:[10000,10000,10]});
 const d=await context('high',null,list,opts());let editor,viewer;
 oneChart(d);
 try{
  await ready(d);await d.controller.start();
  const key=d.controller.state().key,m=d.server.manifests.get(key);
  assert.equal(Object.keys(m.lights).length,6);assert.equal(Object.keys(m.realtime).length,2);
  assert.deepEqual(Object.values(m.realtime).map(e=>e.reason).sort(),['fallback','no reach']);
  assert.equal(m.complete,true);assert.match(output(d).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);
  assert.equal(d.controller.state().stale.length,0);assert.equal(d.controller.fresh().length,6);
  editor=await context('high',d.server,list,opts());oneChart(editor);await ready(editor);
  assert.equal(output(editor).textContent,'Lighting is up to date');
  viewer=await context('high',d.server,list,{mode:'readonly',parent:true,poll:0,host:new Node('div')});oneChart(viewer);
  // The metadata includes round 42 in both real page mounts.
  viewer.view.round=42;
  await until(()=>!!viewer.controller.packing(),'viewer layout');await viewer.controller.refresh();
  assert.equal(viewer.controller.state().stale.length,0);assert.equal(viewer.controller.fresh().length,6);
  assert.ok(!viewer.host.textContent.includes('Lighting is out of date'));
  const fallback=Object.keys(m.realtime).find(id=>m.realtime[id].reason==='fallback');
  const moved=list.map(l=>l.device===fallback?{...l,at:[...l.at.slice(0,2),l.at[2]+.1]}:l);
  editor.view.live={layout:()=>liveLayout(moved)};viewer.view.live={layout:()=>liveLayout(moved)};
  await editor.controller.refresh();await viewer.controller.refresh();
  assert.deepEqual(editor.controller.state().stale,[fallback]);assert.ok(viewer.controller.state().stale.includes(fallback));
 }finally{editor?.controller.stop();viewer?.controller.stop();d.controller.stop();}
});
await check('all_unreached_lights_publish_first_manifest_on_settle_and_reopen_current',async()=>{
 const list=[{...k1,device:'unreached',at:[10000,10000,10]}],d=await context('high',null,list,opts());let next;
 try{
  await ready(d);await d.controller.start();assert.equal(d.renderer.log.renders,0);
  const m=d.server.manifests.get(d.controller.state().key);assert.equal(m.complete,true);
  assert.deepEqual(m.lights,{});assert.equal(m.realtime.unreached.reason,'no reach');
  assert.equal(output(d).textContent,'Lighting is up to date');
  next=await context('high',d.server,list,opts());await ready(next);assert.equal(output(next).textContent,'Lighting is up to date');
 }finally{next?.controller.stop();d.controller.stop();}
});
// The page HTML has no member token, so the server flag is false for a signed-in
// parent. The viewer asks the PARENTS-only latest metadata once, never a lease.
for(const [name,status,link] of [['parent',200,true],['child',403,false]]){
 await check('viewer_without_server_flag_asks_once_and_'+name+(link?'_gets':'_gets_no')+'_stale_link',async()=>{
  const asked=[];let viewer;
  try{
   viewer=await context('high',null,null,{mode:'readonly',parent:false,poll:0,host:new Node('div'),view:{round:42},
     api:(path,init,next)=>{asked.push(path);if(path==='api/house/bakes')return Promise.resolve(new Response('{}',{status}));return next(path,init);}});
   await until(()=>asked.includes('api/house/bakes'),'viewer asks who is looking');
   await until(()=>viewer.controller.state().stale.length===4,'stale with no bake');
   await viewer.controller.refresh();
   assert.equal(/Lighting is out of date/.test(viewer.host.textContent),link);
   assert.equal(asked.filter(p=>p==='api/house/bakes').length,1,'asked once');
   assert.ok(!asked.some(p=>p.endsWith('/lease')),'viewer never checks or takes a lease');
  }finally{viewer?.controller.stop();}
 });
}
await check('viewer_with_server_parent_flag_does_not_ask',async()=>{
 const asked=[];let viewer;
 try{
  viewer=await context('high',null,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{round:42},
    api:(path,init,next)=>{asked.push(path);return next(path,init);}});
  await until(()=>/Lighting is out of date/.test(viewer.host.textContent),'server-flagged parent sees the link');
  assert.ok(!asked.includes('api/house/bakes'));
 }finally{viewer?.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())
