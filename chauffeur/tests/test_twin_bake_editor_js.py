"""Manual editor bake controls and status-only readers through the real runtime."""
import sys
import test_twin_bake_runtime_js as R
DRIVER = R.DRIVER[:R.DRIVER.index("await check(")] + R.DRIVER[R.DRIVER.index("async function retryClock"):R.DRIVER.index("const outputOf =")] + r"""
const outputOf = desk => desk.host.querySelectorAll('output')[0];
const buttonOf = (desk,text) => desk.host.querySelectorAll('button').find(b=>b.textContent===text);
const ready = desk => until(()=>!!desk.controller.packing(),'manual controller ready');
const event = (type,id=1) => Object.assign(new Event(type),{pointerId:id});
await check('empty_editor_reports_current_without_a_bake',async()=>{
 const desk=await context('high',null,null,{mode:'manual',plan:{buildings:[],site:{}},poll:0,host:new Node('div')});
 try {
  await until(()=>outputOf(desk)?.textContent==='Lighting is up to date','empty editor status');
  await desk.controller.start();assert.equal(desk.renderer.log.renders,0);assert.equal(desk.server.writes().length,0);
 }finally{desk.controller.stop();}
});
await check('unlit_keeps_its_fast_no_bake_path_and_says_why',async()=>{
 let reads=0;
 const desk=await context('high',null,null,{mode:'manual',disabledReason:'Switch from Unlit to bake lighting',poll:50,host:new Node('div'),api:(path,init,next)=>{reads++;return next(path,init);}});
 try {
  await until(()=>outputOf(desk)?.textContent==='Switch from Unlit to bake lighting','unlit status');
  await sleep(150);await desk.controller.start();assert.equal(reads,0);assert.equal(desk.renderer.log.renders,0);
  assert.ok(desk.host.querySelectorAll('button').every(b=>b.hidden));
 }finally{desk.controller.stop();}
});
await check('manual_idle_poll_and_relight_never_start_but_button_does',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:50,host:new Node('div')});
 try {
  await ready(desk);await sleep(2200);await desk.controller.refresh();
  assert.equal(desk.renderer.log.renders,0);assert.equal(desk.server.writes().length,0);
  assert.equal(desk.controller.state().baking,false);
  assert.equal(outputOf(desk).textContent,'Lighting out of date: 4 lights');
  const b=buttonOf(desk,'Bake lighting');assert.equal(b.hidden,false);assert.equal(b.disabled,false);
  desk.view.live={layout:()=>liveLayout([k1,k2,h1,{...c1,at:[...c1.at.slice(0,2),c1.at[2]+1]}])};
  await desk.controller.refresh();await sleep(200);
  assert.equal(desk.server.writes().length,0,'relight waits for a person');
  b.dispatchEvent(new Event('click'));
  await until(()=>desk.controller.state().baking&&desk.controller.state().total===4,'button begins whole-house run');
  assert.match(outputOf(desk).textContent,/^Baking lights [0-4] of 4(?: · Grid [1-9]\d* points)?$/);
  assert.ok(!outputOf(desk).textContent.includes('Grid 0 points'));
  assert.equal(desk.host.querySelectorAll('progress')[0].hidden,false);
  await until(()=>desk.controller.fresh().length===4&&!desk.controller.state().baking,'manual bake lands');
  assert.ok(desk.controller.state().grid.points>0);
  assert.ok(desk.controller.state().grid.bytes>0);
  assert.ok(desk.controller.state().grid.ms>0);
  assert.ok(Number.isFinite(desk.controller.state().grid.maskMs)&&desk.controller.state().grid.maskMs>=0);
  const grid=desk.controller.state().grid;
  await desk.controller.refresh();
  assert.deepEqual(desk.controller.state().grid,grid,'idle refresh retains last grid counters');
  assert.equal(outputOf(desk).textContent,`Lighting is up to date · Grid ${grid.points} points, ${Math.ceil(grid.bytes/1024)} KB`);
  assert.equal(b.hidden,true);assert.equal(buttonOf(desk,'Re-bake all lighting').hidden,false);
  assert.equal(buttonOf(desk,'Re-bake all lighting').disabled,false);
 }finally{desk.controller.stop();}
});

await check('manual_no_display_reports_crowded_models_and_zero_hides_suffix',async()=>{
 for(const n of [8,9]) {
  const plan=structuredClone(job.plan);
  const at=lot([9.3,5.2,4]);
  plan.site={...plan.site,furniture:[{id:'stats-chair',asset:'import-missing-stats',at:at.slice(0,2),elevation:at[2]}]};
  const lamps=Array.from({length:n},(_,i)=>({...k1,device:`crowd-${i}`,at:lot([9.3+i*.01,5.2,9.8])}));
  const desk=await context('high',null,lamps,{mode:'manual',display:false,plan,poll:0,host:new Node('div')});
  try {
   await desk.controller.start();
   assert.equal(desk.controller.models,null,'editor does not mount model lighting');
   assert.equal(desk.controller.state().error,null);
   const grid=desk.controller.state().grid;
   assert.equal(grid.foldedOrDropped,n===9?1:0);
   assert.equal(outputOf(desk).textContent,`Lighting is up to date \u00b7 Grid ${grid.points} points, ${Math.ceil(grid.bytes/1024)} KB${n===9?' \u00b7 1 models folded or dropped lamps':''}`);
   const chunks=[...desk.server.grids.values()];
   const {decodeGridChunk}=await import(file('static/twin/bake/grid_chunk.js'));
   let totalPoints=0,totalBytes=0;
   for(const bytes of chunks){totalPoints+=(await decodeGridChunk(bytes)).indices.length;totalBytes+=bytes.length;}
   assert.equal(grid.points,totalPoints,'settled points sum all chunks in the run');assert.equal(grid.bytes,totalBytes);
   if(n===9){
    const before=desk.server.calls.length;await desk.controller.start();
    assert.equal(desk.controller.state().grid.foldedOrDropped,1,'settle also counts against reused chunks');
    assert.match(outputOf(desk).textContent,/1 models folded or dropped lamps$/);
    assert.ok(!desk.server.calls.slice(before).some(c=>c.method==='POST'&&c.path.endsWith('.png')),'stats-only settle keeps pages');
   }

  }finally{desk.controller.stop();}
 }
});


await check('manual_complete_pages_offer_grid_only_button_for_old_or_missing_grids',async()=>{
 const seed=await context('high',null,null,{mode:'manual',display:false,poll:0,host:new Node('div')});
 try{
  await seed.controller.start();
  const key=seed.controller.state().key,initial=structuredClone(seed.server.manifests.get(key));
  for(const defect of ['old-rule','missing-name','missing-file']){
   seed.server.manifests.set(key,structuredClone(initial));const m=seed.server.manifests.get(key);
   if(defect==='old-rule')for(const e of Object.values(m.lights))delete e.gridRule;
   if(defect==='missing-name')for(const e of Object.values(m.lights))delete e.grid;
   if(defect==='missing-file')for(const e of Object.values(m.lights))seed.server.grids.delete(`${key}/${e.grid}`);
   const before=seed.server.calls.length,pages=new Map(seed.server.pages);
   const desk=await context('high',seed.server,null,{mode:'manual',display:false,poll:0,host:new Node('div')});
   try{
    await until(()=>outputOf(desk)?.textContent==='Lighting grid out of date: 4 lights','cheap grid status '+defect);
    assert.deepEqual(desk.controller.state().stale,[],'pages remain fresh');
    assert.equal(desk.controller.packing(),null,'idle check never builds atlas');
    const button=buttonOf(desk,'Bake lighting');assert.equal(button.hidden,false);assert.equal(button.disabled,false);
    await sleep(100);await desk.controller.refresh();assert.equal(seed.server.writes(before).length,0,'poll never bakes');
    assert.equal(desk.renderer.log.renders,0,'idle check never renders');
    button.dispatchEvent(new Event('click'));
    await until(()=>desk.controller.state().baked.length===4&&!desk.controller.state().baking,'grid-only button lands '+defect);
    assert.equal(desk.controller.state().error,null);
    const writes=seed.server.writes(before);
    assert.equal(writes.filter(c=>c.method==='POST'&&c.path.includes('/grid/')).length,4);
    assert.ok(!writes.some(c=>c.path.endsWith('.png')),'no page writes');assert.deepEqual(seed.server.pages,pages);
    assert.equal(buttonOf(desk,'Bake lighting').hidden,true,JSON.stringify({defect,status:outputOf(desk).textContent,state:desk.controller.state()}));assert.match(outputOf(desk).textContent,/^Lighting is up to date/);
   }finally{desk.controller.stop();}
  }
 }finally{seed.controller.stop();}
});
await check('manual_stats_read_failure_warns_once_and_never_retries_published_bake',async()=>{
 const plan=structuredClone(job.plan),at=lot([9.3,5.2,0]);
 plan.site={...plan.site,furniture:[{id:'floor-copy',asset:'import-missing-stats',at:at.slice(0,2),elevation:at[2]}]};
 const lamps=Array.from({length:9},(_,i)=>({...k1,device:`stats-${i}`,at:lot([9.3+i*.01,5.2,9.8])}));
 let broken=false,warnings=0;const warn=console.warn;
 const desk=await context('high',null,lamps,{mode:'manual',display:false,plan,poll:0,host:new Node('div'),api:(path,init,next)=>{
  const h=new Headers(init?.headers);if(broken&&path.includes('/grid/')&&h.get('If-None-Match')!=='*')return Promise.resolve(new Response('{}',{status:503}));
  return next(path,init);
 }});
 try{
  await desk.controller.start();assert.equal(desk.controller.state().grid.foldedOrDropped,1,'nominal box sits above the floor');
  broken=true;console.warn=()=>{warnings++;};
  const since=desk.server.calls.length;await desk.controller.start();
  assert.equal(warnings,1);assert.equal(desk.controller.state().error,null);assert.equal(desk.controller.state().retryAt,null);
  assert.equal(desk.controller.state().grid.foldedOrDropped,0);assert.ok(!outputOf(desk).textContent.includes('folded or dropped'));
  assert.ok(desk.server.manifests.get(desk.controller.state().key).complete);
  await sleep(100);assert.equal(desk.server.writes(since).length,0,'no retry writes after optional stats failure');
 }finally{console.warn=warn;desk.controller.stop();}
});

await check('manual_drag_pauses_every_render_slice_then_resumes',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:0,host:new Node('div')});
 try {
  await ready(desk);
  desk.view.bakePlan=desk.view.plan;const authored=desk.view.plan;
  desk.renderer.domElement.dispatchEvent(event('pointerdown'));
  desk.view.plan=structuredClone(authored);desk.view.plan.buildings[0].walls[0].from[0]+=.1;
  const run=desk.controller.start();await until(()=>desk.controller.state().baking,'run waits during drag');
  const before=desk.renderer.log.renders;await sleep(2200);
  assert.equal(desk.controller.state().paused,true);assert.equal(desk.renderer.log.renders,before);
  desk.view.plan=authored;
  window.dispatchEvent(event('pointerup'));await sleep(100);assert.equal(desk.renderer.log.renders,before);
  await run;assert.equal(desk.controller.fresh().length,4);
 }finally{desk.controller.stop();}
});
await check('manual_bake_publishes_grids_independent_of_live_palette',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:0,host:new Node('div')});
 try {
  await ready(desk);
  desk.view.live={layout:()=>liveLayout([k1,k2,h1,c1]),paletteLines:()=>['k1']};
  await desk.controller.start();
  const lights=desk.server.manifests.get(desk.controller.state().key).lights;
  assert.ok(lights.k1.grid&&lights.k1.gridLayout,'live palettes cannot exclude bake grids');
  assert.ok(lights.k2.grid&&lights.k2.gridLayout,'ordinary lights still publish grids');
 }finally{desk.controller.stop();}
});
await check('manual_light_edit_stales_only_that_light_without_restart',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:0,host:new Node('div')});
 try {
  await ready(desk);await desk.controller.start();const key=desk.controller.state().key,since=desk.server.calls.length;
  desk.view.live={layout:()=>liveLayout([k1,k2,h1,{...c1,at:[c1.at[0]+1,c1.at[1],c1.at[2]]}])};
  await desk.controller.refresh();await sleep(100);
  assert.equal(desk.controller.state().key,key);assert.deepEqual(desk.controller.state().stale,['c1']);
  assert.equal(outputOf(desk).textContent,'Lighting out of date: 1 light');
  assert.equal(desk.server.writes(since).length,0);
  await desk.controller.start();assert.deepEqual(desk.controller.state().baked.slice(4),['c1']);
 }finally{desk.controller.stop();}
});
await check('geometry_key_change_stops_at_checkpoint_preserves_saved_lights_and_waits',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:0,host:new Node('div')});let next;
 try {
  await ready(desk);const oldKey=desk.controller.state().key;
  let stopped=false;
  const idle=desk.controller.idle;
  desk.controller.idle=async()=>{
   await idle();
   if(!stopped&&Object.keys(desk.server.manifests.get(oldKey)?.lights||{}).length===1){
    stopped=true;desk.view.plan=structuredClone(desk.view.plan);desk.controller.stop();
   }
  };
  await desk.controller.start();assert.ok(stopped);
  assert.equal(Object.keys(desk.server.manifests.get(oldKey).lights).length,1);
  const oldBytes=new Map(desk.server.pages),before=desk.server.calls.length;
  const plan=structuredClone(job.plan);plan.buildings[0].walls[0].from[0]+=.1;
  next=await context('high',desk.server,null,{mode:'manual',plan,poll:50,host:new Node('div')});
  await ready(next);await sleep(2200);
  assert.notEqual(next.controller.state().key,oldKey);assert.equal(next.controller.state().baking,false);
  assert.equal(desk.server.writes(before).length,0);
  assert.equal(outputOf(next).textContent,'Lighting out of date: 4 lights');
  for(const [key,bytes] of oldBytes)assert.deepEqual(desk.server.pages.get(key),bytes);
 }finally{desk.controller.stop();next?.controller.stop();}
});
await check('manual_tier_and_child_rules',async()=>{
 for(const mode of ['low','medium','child']){
  const desk=await context(mode==='child'?'high':mode,null,null,{mode:'manual',deny:mode==='child',poll:0,host:new Node('div')});
  try {
   await until(()=>outputOf(desk)?.textContent===(mode==='child'?'Only a parent can bake lighting':'Baking needs High or Max quality'),'permission status');
   assert.equal(desk.controller.state().key,null,'disallowed desks do no atlas work');
   assert.equal(outputOf(desk).textContent,mode==='child'?'Only a parent can bake lighting':'Baking needs High or Max quality');
   assert.ok(desk.host.querySelectorAll('button').every(b=>b.hidden));
   await desk.controller.start();await desk.controller.now();await desk.controller.resume();
   assert.equal(desk.server.writes().length,0);assert.equal(desk.renderer.log.renders,0);
  }finally{desk.controller.stop();}
 }
});
await check('viewer_has_no_lease_or_actions_and_only_parent_gets_ingress_safe_link',async()=>{
 const seed=await context('high',null,null,{mode:'manual',poll:0});await ready(seed);
 try {
  for(const who of ['parent','child','panel','kiosk']){
   location.search=['panel','kiosk'].includes(who)?'?'+who+'=true':'';
   const since=seed.server.calls.length;
   // The server flag is false for a page load; the real PARENTS rule refuses a child's metadata read.
   const reader=await context('high',seed.server,null,{mode:'readonly',parent:who==='panel'||who==='kiosk',poll:50,host:new Node('div'),
     api:(path,init,next)=>who==='child'&&path==='api/house/bakes'?Promise.resolve(new Response('{"detail":"Requires parent"}',{status:403})):next(path,init)});
   location.search='';
   try {
    await until(()=>reader.controller.state().key,'viewer atlas read');await sleep(200);
    await reader.controller.start();await reader.controller.now();await reader.controller.resume();
    assert.equal(reader.host.querySelectorAll('button').length,0);
    const links=reader.host.querySelectorAll('a');assert.equal(links.length,who==='parent'?1:0);
    if(links.length){assert.equal(links[0].textContent,'Lighting is out of date. Bake it in the house editor.');assert.equal(links[0].href,'../house/editor');}
    assert.ok(!seed.server.calls.slice(since).some(c=>c.path.endsWith('/lease')),'viewer never even checks a lease');
    assert.equal(seed.server.writes(since).length,0);
   }finally{reader.controller.stop();}
  }
  await seed.controller.start();
  const since=seed.server.calls.length;
  const reader=await context('high',seed.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div')});
  try {
   await until(()=>reader.controller.fresh().length===4,'viewer draws editor bake');
   assert.equal(reader.host.querySelectorAll('a').length,0,'current bake hides status');
   assert.ok(!seed.server.calls.slice(since).some(c=>c.path.endsWith('/lease')));
  }finally{reader.controller.stop();}
 }finally{seed.controller.stop();}
});
await check('manual_401_pauses_and_resume_preserves_saved_lights',async()=>{
 const server=fakeServer();let expired=false;
 const desk=await context('high',server,null,{mode:'manual',poll:50,host:new Node('div'),api:(path,init,next)=>expired&&path.includes('/bakes/')?Promise.resolve(new Response('',{status:401})):next(path,init)});
 try {
  await ready(desk);
  observeEncode=()=>{if(Object.keys([...server.manifests.values()][0]?.lights||{}).length===1)expired=true;};
  await desk.controller.start();observeEncode=null;
  assert.equal(desk.controller.state().paused,true);assert.equal(desk.controller.state().retryAt,null);
  assert.match(outputOf(desk).textContent,/^Home Assistant signed this tab out/);
  assert.equal(buttonOf(desk,'Resume').hidden,false);
  expired=false;await desk.controller.resume();
  assert.deepEqual(desk.controller.state().baked,['k1','k2','h1','c1']);
 }finally{observeEncode=null;desk.controller.stop();}
});
await check('manual_retry_continues_only_a_button_requested_run',async()=>retryClock(async advance=>{
 const server=fakeServer();let broken=true;
 server.fail=(method,path)=>broken&&method==='POST'&&path.endsWith('.png')?503:null;
 const desk=await context('high',server,null,{mode:'manual',poll:50,host:new Node('div')});
 try {
  await ready(desk);await advance(60000);await desk.controller.refresh();
  assert.equal(desk.controller.state().retryAt,null);assert.equal(server.writes().length,0);
  await desk.controller.start();assert.equal(desk.controller.state().retryAttempts,1);
  assert.match(outputOf(desk).textContent,/Retrying in 5 s/);
  broken=false;await advance(5000);
  await until(()=>desk.controller.fresh().length===4&&!desk.controller.state().baking,'requested retry lands');
 }finally{desk.controller.stop();}
}));
await check('manual_force_reload_waits_and_resume_keeps_force_progress',async()=>{
 const desk=await context('high',null,null,{mode:'manual',poll:0,host:new Node('div')});let next;
 try {
  await ready(desk);await desk.controller.start();const server=desk.server,key=desk.controller.state().key;
  let failed=false;
  server.fail=(method,path)=>{
   const m=server.manifests.get(key);
   if(!failed&&method==='POST'&&path.endsWith('.png')&&m.forceRound&&Object.values(m.lights).filter(e=>e.forceRound===m.forceRound).length===2){failed=true;return 503;}
  };
  await desk.controller.now();desk.controller.stop();server.fail=null;
  const saved=structuredClone(server.manifests.get(key)),before=server.calls.length;
  next=await context('high',server,null,{mode:'manual',poll:50,host:new Node('div')});
  await ready(next);await until(()=>next.controller.state().done===2,'stored force progress read');await sleep(2200);
  assert.equal(next.controller.state().baking,false);assert.equal(server.writes(before).length,0);
  assert.equal(buttonOf(next,'Resume').hidden,false);assert.equal(next.controller.state().stale.length,2);
  buttonOf(next,'Resume').dispatchEvent(new Event('click'));
  await until(()=>next.controller.state().done===4&&!next.controller.state().baking,'force resumed');
  assert.deepEqual(next.controller.state().baked,['h1','c1']);
  for(const id of ['k1','k2'])assert.deepEqual(server.manifests.get(key).lights[id],saved.lights[id]);
 }finally{desk.controller.stop();next?.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER=DRIVER
    sys.exit(R.run())
