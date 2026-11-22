"""Fix round 2: polling, lease fencing and silent readers through production modules."""
import sys
import test_twin_bake_fix1_js as F

R = F.R
DRIVER = F.DRIVER[:F.DRIVER.index("await check(")]
DRIVER += R.DRIVER[R.DRIVER.index("async function retryClock"):R.DRIVER.index("const outputOf =")]
DRIVER += r"""
await check('poll_keeps_bake_failure_countdown_and_resume',async()=>retryClock(async advance=>{
 const server=fakeServer({leaseRequired:true});let failures=0;
 server.fail=(method,path)=>method==='POST'&&path.endsWith('.png')&&
   Object.keys([...server.manifests.values()][0]?.lights||{}).length===2&&failures++<3?503:null;
 const desk=await context('high',server,null,{poll:50,host:new Node('div')});
 try{
   const failed=()=>!!desk.controller.state().error&&!desk.controller.state().baking;
   await until(failed,'first failure');await advance(5000);await until(failed,'second failure');
   await advance(15000);await until(failed,'third failure');
   const deadline=desk.controller.state().retryAt,reason=desk.controller.state().error;
   assert.ok(deadline>Date.now()+59000,'third failure waits sixty seconds');
   await desk.controller.refresh();await sleep(150); // includes successful normal polls
   assert.equal(desk.controller.state().error,reason);assert.equal(desk.controller.state().retryAt,deadline);
   assert.match(outputOf(desk).textContent,/Could not bake lighting.*Retrying in 60 s/);
   assert.equal(buttonsOf(desk)[1].hidden,false,'Resume survives successful polls');
   await advance(10000);await desk.controller.refresh();
   assert.match(outputOf(desk).textContent,/Retrying in 50 s/);
   await advance(50000);await until(()=>desk.controller.state().done===4&&!desk.controller.state().baking,'plain retry finishes');
   assert.equal(desk.controller.state().error,null);assert.equal(buttonsOf(desk)[1].hidden,true);
   assert.deepEqual(desk.controller.state().baked,['k1','k2','h1','c1']);
 }finally{desk.controller.stop();}
}));
await check('lease_age_uses_acquire_and_renew_send_times',async()=>{
 const nativeSet=setInterval,nativeClear=clearInterval,now=Date.now;let tick,clock=0,count=0,delayedAcquire=true,worked=false;
 globalThis.setInterval=fn=>{tick=fn;return {};};globalThis.clearInterval=()=>{};Date.now=()=>clock;
 const api=async(path,init)=>{
   if(JSON.parse(init.body).action==='release')return new Response('{}');
   count++;if(delayedAcquire)clock=41000;else if(count>1)clock=55000;
   return new Response('{"held":true}');
 };
 try{
   await assert.rejects(withBakeLease(api,'key','desk',()=>true,async()=>{worked=true;}),/lease expired/);
   assert.equal(worked,false,'an acquisition delayed beyond forty seconds cannot start work');
   delayedAcquire=false;clock=count=0;
   await assert.rejects(withBakeLease(api,'key','desk',()=>true,async check=>{
     clock=20000;tick();await check(); // response at 55s; renewal was sent at 20s
     clock=59000;await check();clock=60000;await check();
   }),/lease expired/);
 }finally{globalThis.setInterval=nativeSet;globalThis.clearInterval=nativeClear;Date.now=now;}
});
await check('failed_renewals_lose_lease_at_forty_seconds',async()=>{
 const nativeSet=setInterval,nativeClear=clearInterval,now=Date.now;let tick,clock=0,count=0;
 globalThis.setInterval=fn=>{tick=fn;return {};};globalThis.clearInterval=()=>{};Date.now=()=>clock;
 const api=async(path,init)=>JSON.parse(init.body).action==='release'||++count===1
   ?new Response('{"held":true}'):new Response('',{status:503});
 try{
   await assert.rejects(withBakeLease(api,'key','desk',()=>true,async check=>{
     clock=20000;tick();await check();clock=39999;await check();clock=40000;await check();
   }),/HTTP 503/);
 }finally{globalThis.setInterval=nativeSet;globalThis.clearInterval=nativeClear;Date.now=now;}
});
await check('write_owner_and_conflict_abort_without_light_receipt',async()=>{
 for(const conflict of ['POST','PUT']){
   const ctx=await setup(),server=fakeServer({leaseRequired:true}),list=[k1,k2];let armed=false,refused=false;
   const api=async(path,init)=>{
     if(['POST','PUT'].includes(init?.method)&&!path.endsWith('/lease')){
       assert.equal(new Headers(init.headers).get('X-Bake-Owner'),'desk');
       if(armed&&init.method===conflict&&!refused){server.lease.holder='other';refused=true;}
     }
     return server.api(path,init);
   };
   const baker=B.createBaker(ctx.view,{renderer:ctx.renderer,atlas:ctx.atlas,layout:ctx.layout,lights:list,codec,api,owner:'desk'});
   assert.equal(await baker.bakeNext(),'k1');
   const saved=structuredClone(server.manifests.get(ctx.atlas.key)),before=server.calls.length;armed=true;
   await assert.rejects(baker.bakeNext(),e=>e.status===409&&/Lost the bake lease/.test(e.message));
   assert.ok(refused);assert.deepEqual(server.manifests.get(ctx.atlas.key),saved,'no unsaved light receipt');
   assert.equal(server.manifests.get(ctx.atlas.key).lights.k2,undefined);
   if(conflict==='POST')assert.equal(server.calls.slice(before).filter(c=>c.method==='PUT').length,0,'page refusal stops manifest publication');
 }
});
await check('readonly_failures_and_recovery_leave_no_lighting_strip',async()=>{
 const seed=await context('high',null,null,{poll:0});
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');seed.controller.stop();
   for(const mode of ['panel','kiosk','low','child']){
     let broken=false;location.search=['panel','kiosk'].includes(mode)?`?${mode}=true`:'';
     const reader=await context(mode==='low'?'low':'high',seed.server,null,{poll:50,deny:mode==='child',host:new Node('div'),
       api:(path,init,next)=>broken&&path.includes('/bakes/')?Promise.resolve(new Response('',{status:401})):next(path,init)});
     location.search='';
     try{
       await until(()=>reader.controller.fresh().length===4,'reader loads');broken=true;
       await until(()=>!!reader.controller.state().error,'read failure observable');
       assert.equal(reader.host.children.length,0,mode+' has no strip during failure');
       assert.equal(outputOf(reader),undefined);assert.equal(buttonsOf(reader).length,0);
       broken=false;await until(()=>!reader.controller.state().error,'reader recovers');
       assert.equal(reader.host.children.length,0,mode+' leaves no empty strip');assert.equal(reader.renderer.log.renders,0);
     }finally{reader.controller.stop();}
   }
 }finally{location.search='';seed.controller.stop();}
});
await check('permission_resolution_removes_an_existing_status_strip',async()=>{
 const seed=await context('high',null,null,{poll:0});let reader;
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');seed.controller.stop();
   let fail=true;
   reader=await context('high',seed.server,null,{poll:0,deny:true,host:new Node('div'),api:(path,init,next)=>{
     if(fail&&path==='api/house/live'){fail=false;throw new Error('initial connection failure');}
     return next(path,init);
   }});
   await until(()=>!!reader.controller.state().error,'initial permission check has not run');
   assert.equal(reader.host.children.length,1,'candidate desk can explain a failed mount');
   await reader.controller.refresh();
   assert.equal(reader.controller.state().error,null);assert.equal(reader.host.children.length,0,'resolved child view removes the old strip');
   assert.equal(reader.renderer.log.renders,0);
 }finally{seed.controller.stop();reader?.controller.stop();}
});
await check('child_read_failure_during_mount_stays_silent_and_recovers',async()=>{
 const seed=await context('high',null,null,{poll:0});let reader;
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');seed.controller.stop();
   let broken=true;
   reader=await context('high',seed.server,null,{poll:50,deny:true,host:new Node('div'),api:(path,init,next)=>
     broken&&path.endsWith('.png')?Promise.resolve(new Response('',{status:401})):next(path,init)});
   await until(()=>!!reader.controller.state().error,'read fails after child permission is known');
   assert.equal(reader.host.children.length,0);assert.equal(reader.controller.state().paused,false);
   assert.equal(reader.controller.state().retryAt,null);broken=false;
   await until(()=>reader.controller.fresh().length===4&&!reader.controller.state().error,'normal mount poll recovers');
   assert.equal(reader.host.children.length,0);assert.equal(reader.renderer.log.renders,0);
 }finally{seed.controller.stop();reader?.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""

if __name__ == '__main__':
    R.DRIVER = DRIVER
    sys.exit(R.run())
