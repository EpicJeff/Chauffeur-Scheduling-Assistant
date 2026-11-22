"""Fix-round regression checks through the real bake runtime (no browser)."""
import sys
import test_twin_bake_runtime_js as R
DRIVER = R.DRIVER[:R.DRIVER.index("await check(")] + R.DRIVER[R.DRIVER.index("async function retryClock"):R.DRIVER.index("const outputOf =")] + r"""
const output = d => d.host.querySelectorAll('output')[0];
const buttons = d => d.host.querySelectorAll('button');
const opts = extra => ({mode:'manual',display:false,poll:0,host:new Node('div'),...extra});
const ready = d => until(()=>d.controller.state().key && /^Lighting /.test(output(d)?.textContent),'editor inspection ready');
const event = (type,id=71)=>Object.assign(new Event(type),{pointerId:id});
await check('1_press_waits_for_the_deferred_yard_before_keying_or_baking',async()=>{
 const d=await context('high',null,null,opts({view:{yardSettling:true}}));
 try {
  const run=d.controller.start();await sleep(2300);
  assert.equal(d.controller.state().key,null);assert.equal(d.server.writes().length,0);
  d.view.yardSettling=false;await run;
  assert.equal(d.controller.fresh().length,4);assert.ok(d.server.writes().length);
 }finally{d.controller.stop();}
});
await check('2_impossible_desks_do_no_atlas_work_and_edits_wait_for_idle_without_transcodes',async()=>{
 const {registerBakeSource}=await import(file('static/twin/bake/source.js'));
 let neutral=0,physical=0,transcodes=0;
 const Worker=globalThis.Worker;
 globalThis.Worker=class {constructor(url,options){
  const worker=new Worker(url,options),post=worker.postMessage.bind(worker);
  worker.postMessage=job=>{if(job.kind==='transcode')transcodes++;return post(job);};return worker;
 }};
 try {
  for(const extra of [{deny:true},{tier:'low'},{tier:'medium'},{disabledReason:'Switch from Unlit to bake lighting'}]){
   for(let edit=0;edit<3;edit++){
    const d=await context(extra.tier||'high',null,null,opts(extra));
    registerBakeSource(d.out.root,()=>{neutral++;return gen.buildTwin(d.view.plan,job.kit,'high',{bakeSource:true}).root;});
    await sleep(edit===2?2200:30);assert.equal(d.controller.state().key,null);d.controller.stop();
   }
  }
  assert.equal(neutral,0);assert.equal(physical,0);assert.equal(transcodes,0);
  for(let edit=0;edit<3;edit++){
   let releaseLive,liveWaiting=false;const heldLive=new Promise(resolve=>releaseLive=resolve);
   const d=await context('high',null,null,opts({api:async(path,init,next)=>{
    if(edit===2&&path==='api/house/live'&&!liveWaiting){liveWaiting=true;await heldLive;}return next(path,init);
   }}));
   registerBakeSource(d.out.root,()=>{neutral++;return gen.buildTwin(d.view.plan,job.kit,'high',{bakeSource:true}).root;},
    {alphaRoots:()=>[d.out.root],receiverRoots:()=>{physical++;return [gen.buildTwin(d.view.plan,job.kit,'high',{bakeSource:true}).root];}});
   document.dispatchEvent(event('pointerdown'));
   await sleep(80);assert.equal(neutral,0);assert.equal(physical,0);
   if(edit<2){d.controller.stop();continue;}
   document.dispatchEvent(event('pointerup'));
   await until(()=>liveWaiting,'live read begins after initial idle');
   document.dispatchEvent(event('pointerdown'));releaseLive();await sleep(100);
   assert.equal(neutral,0,'a gesture starting during the live fetch also defers generation');
   document.dispatchEvent(event('pointerup'));await ready(d);
   assert.equal(neutral,1);assert.equal(physical,1,'physical viewer keys are computed after idle');assert.equal(transcodes,0);assert.equal(d.controller.held(),null);
   await d.controller.start();assert.equal(physical,1);assert.equal(transcodes,0);assert.equal(d.controller.held(),null);
   const key=d.controller.state().key;assert.ok(d.server.manifests.get(key).lights.k1.key);assert.equal(d.server.manifests.get(key).lights.k1.input,undefined);
   await d.controller.refresh();assert.equal(d.controller.fresh().length,4);
   d.view.live={layout:()=>liveLayout([k1,k2,h1,{...c1,at:[c1.at[0]+1,...c1.at.slice(1)]}])};
   await d.controller.refresh();assert.deepEqual(d.controller.state().stale,['c1']);
   const page=d.server.manifests.get(key).lights.k1.pages[0];d.server.pages.delete(key+'/'+page);d.server.manifests.get(key).pageRevision=1;
   await d.controller.refresh();assert.ok(d.controller.state().stale.includes('k1'),'missing pages invalidate their lights without a transcode');
   assert.equal(transcodes,0);d.controller.stop();
  }
 }finally{globalThis.Worker=Worker;}
});
await check('3_unsaved_saving_and_history_gates_disable_every_action_and_stop_a_run',async()=>{
 let reason='Saving edits; bake when they land';
 const d=await context('high',null,null,opts({blocked:()=>reason}));
 try {
  assert.equal(output(d).textContent,reason);assert.ok(buttons(d).every(b=>b.disabled));
  await d.controller.start();assert.equal(d.server.writes().length,0);
  reason='Back to now to bake';d.controller.syncBlocked();assert.equal(output(d).textContent,reason);
  await d.controller.now();await d.controller.resume();assert.equal(d.server.writes().length,0);
  reason='';d.controller.syncBlocked();await ready(d);
  const idle=d.controller.idle;let stopped=false;
  d.controller.idle=async()=>{await idle();if(!stopped){stopped=true;reason='Saving edits; bake when they land';d.controller.syncBlocked();}};
  await d.controller.start();assert.ok(stopped);assert.equal(d.controller.state().baking,false);
  assert.notEqual(d.server.manifests.get(d.controller.state().key)?.complete,true);
  assert.equal(output(d).textContent,reason);assert.ok(buttons(d).every(b=>b.disabled));
  reason='';d.controller.syncBlocked();await d.controller.refresh();await sleep(100);
  assert.equal(d.controller.state().baking,false);
 }finally{d.controller.stop();}
});
await check('4_poll_failure_after_a_completed_press_never_starts_a_bake_or_offers_resume',async()=>retryClock(async advance=>{
 let broken=false;const log=console.error;console.error=()=>{};
 const d=await context('high',null,null,opts({poll:50,api:(path,init,next)=>broken&&/^api\/house\/bakes\/[^/]+$/.test(path)?Promise.reject(new Error('poll read failed')):next(path,init)}));
 try {
  await ready(d);await d.controller.start();const before=d.server.calls.length;
  broken=true;
  await until(()=>/^Could not read baked lighting/.test(output(d)?.textContent),'read error wording');
  assert.equal(buttons(d).find(b=>b.textContent==='Resume').hidden,true);
  const key=d.controller.state().key,page=d.server.manifests.get(key).lights.k1.pages[0];
  d.server.pages.delete(key+'/'+page);d.server.manifests.get(key).pageRevision=1;
  broken=false;await advance(200000);await d.controller.refresh();await sleep(300);
  assert.equal(d.server.writes(before).length,0);assert.equal(d.controller.state().baking,false);
  assert.ok(d.controller.state().stale.includes('k1'));
  assert.ok(!d.server.calls.slice(before).some(c=>c.path.endsWith('/lease')),'a recovered poll cannot take a bake lease to repair a missing page');
 }finally{d.controller.stop();console.error=log;}
}));
await check('5_first_read_has_no_stale_flash_and_publications_refresh_both_statuses',async()=>{
 let release;const held=new Promise(r=>release=r);
 const seed=await context('high',null,null,opts());await ready(seed);await seed.controller.start();
 const desk=await context('high',seed.server,null,opts({api:async(path,init,next)=>{if(/^api\/house\/bakes\/[^/]+$/.test(path))await held;return next(path,init);}}));
 const viewer=await context('high',seed.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),api:async(path,init,next)=>{if(/^api\/house\/bakes\/[^/]+$/.test(path))await held;return next(path,init);}});
 try {
  await sleep(2300);assert.doesNotMatch(output(desk)?.textContent||'',/out of date/);assert.equal(viewer.host.querySelectorAll('a').length,0);
  release();await until(()=>desk.controller.fresh().length===4,'editor adopts manifest');await until(()=>viewer.controller.fresh().length===4,'viewer adopts manifest');
  assert.equal(output(desk).textContent,'Lighting is up to date');assert.equal(viewer.host.querySelectorAll('a').length,0);
  const key=seed.controller.state().key,saved=structuredClone(seed.server.manifests.get(key));
  seed.server.manifests.delete(key);await desk.controller.refresh();await viewer.controller.refresh();
  assert.equal(output(desk).textContent,'Lighting out of date: 4 lights');assert.equal(viewer.host.querySelectorAll('a').length,1);
  seed.server.manifests.set(key,saved);await desk.controller.refresh();await viewer.controller.refresh();
  assert.equal(output(desk).textContent,'Lighting is up to date');assert.equal(viewer.host.querySelectorAll('a').length,0);
 }finally{release();desk.controller.stop();viewer.controller.stop();seed.controller.stop();}
});
await check('6_spend_and_estimate_are_absent_without_build_state',async()=>{
 const {createStatusChip}=await import(file('static/twin/editor/status_chip.js'));
 const host=new Node('div'),chip=createStatusChip(host);
 chip.update({state:null,cost:0,estimate:4});assert.equal(host.children[1].hidden,true);assert.equal(host.children[2].hidden,true);
 chip.update({state:'running',cost:0,estimate:4});assert.equal(host.children[1].hidden,false);assert.equal(host.children[2].hidden,false);
 chip.update({state:'done',cost:3,estimate:null});assert.equal(host.children[1].hidden,true);assert.equal(host.children[2].hidden,true);
});
await check('7_document_library_and_splitter_drags_pause_render_to_texture',async()=>{
 const d=await context('high',null,null,opts());
 try {
  await ready(d);document.dispatchEvent(event('pointerdown'));const run=d.controller.start();
  await until(()=>d.controller.state().baking,'pressed run waiting on dock gesture');await sleep(2100);
  assert.equal(d.renderer.log.renders,0);assert.equal(d.controller.state().paused,true);
  document.dispatchEvent(event('pointercancel'));await run;assert.equal(d.controller.fresh().length,4);
 }finally{d.controller.stop();}
});
await check('8_viewer_parents_keep_damage_and_gpu_overflow_information_without_actions',async()=>{
 const seed=await context('high',null,null,opts());await ready(seed);await seed.controller.start();
 try {
  const key=seed.controller.state().key,page=seed.server.manifests.get(key).lights.k1.pages[0];
  const bytes=seed.server.pages.get(key+'/'+page);seed.server.pages.set(key+'/'+page,new Uint8Array([0,1,2]));
  for(const who of ['parent','child','panel','kiosk']){
   location.search=['panel','kiosk'].includes(who)?'?'+who+'=true':'';
   const d=await context('high',seed.server,null,{mode:'readonly',parent:who!=='child',poll:0,host:new Node('div')});location.search='';
   try {
    await until(()=>!!d.controller.state().error,'damaged page reported');
    assert.equal(d.host.querySelectorAll('button').length,0);
    assert.equal(d.host.querySelectorAll('a').length,who==='parent'?1:0);
    if(who==='parent')assert.match(d.host.children[0].children.map(n=>n.textContent).join(''),/Lightmap page/);
   }finally{d.controller.stop();}
  }
  seed.server.pages.set(key+'/'+page,bytes);
  const overflow=await context('high',seed.server,null,{mode:'readonly',parent:true,maxArrayLayers:1,poll:0,host:new Node('div')});
  try{await until(()=>/array layers/.test(overflow.controller.state().error||''),'overflow reported');assert.match(overflow.host.children[0].children.map(n=>n.textContent).join(''),/this GPU supports 1/);assert.equal(overflow.host.querySelectorAll('button').length,0);}finally{overflow.controller.stop();}
  const limited=await context('high',seed.server,null,opts({maxArrayLayers:1,view:{live:{draw(){},stop(){}}}}));
  try {
   await ready(limited);const before=seed.server.calls.length;await limited.controller.now();
   assert.match(limited.controller.state().error,/this GPU supports 1/);
   assert.equal(limited.controller.held(),null);assert.equal(seed.server.writes(before).length,0);
  }finally{limited.controller.stop();}
 }finally{seed.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())
