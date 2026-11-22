"""Fix-round regressions through production bake modules; no browser."""
import sys
import test_twin_bake_runtime_js as R

DRIVER = R.DRIVER[:R.DRIVER.index("await check(")]
DRIVER += "const LAYOUT=job.layout;\n"
DRIVER += R.B.DRIVER[R.B.DRIVER.index("async function setup"):R.B.DRIVER.index("const asSet")]
DRIVER += r"""
const {withBakeLease}=await import(file('static/twin/bake/bake_lock.js'));
const outputOf=desk=>desk.host.querySelectorAll('output')[0];
const buttonsOf=desk=>desk.host.querySelectorAll('button');
await check('fix1_force_rounds_follow_server_and_finish',async()=>{
 const ctx=await setup(),server=fakeServer({leaseRequired:true}),list=[k1,k2,h1,c1];
 const a=makeBaker(ctx,server,list,{force:true,owner:'a'}),seen=[];
 seen.push(await a.bakeNext());
 const follower=makeBaker(ctx,server,list,{owner:'follower'});await follower.staleLights();
 const newer=makeBaker(ctx,server,list,{force:true,owner:'newer'});
 seen.push(await newer.bakeNext());
 const newerRound=server.manifests.get(ctx.atlas.key).forceRound;
 for(let i=0;i<12;i++){
   const id=await (i%2?newer:follower).bakeNext();if(id)seen.push(id);
   if(!(await follower.staleLights()).length&&!(await newer.staleLights()).length)break;
 }
 assert.deepEqual(await follower.staleLights(),[]);assert.deepEqual(await newer.staleLights(),[]);
 assert.equal(server.manifests.get(ctx.atlas.key).forceRound,undefined);
 for(const id of list.map(l=>l.device))assert.ok(seen.filter(x=>x===id).length<=2,id+' bounded work');
 assert.ok(Object.values(server.manifests.get(ctx.atlas.key).lights).every(e=>e.forceRound===newerRound));
 // The original force also sees the completed replacement, rather than resurrecting A.
 assert.equal(await a.bakeNext(),null);assert.deepEqual(await a.staleLights(),[]);
 // Settling a model round must not erase a force that started after our read.
 const idle=makeBaker(ctx,server,list,{round:2,owner:'idle'});assert.deepEqual(await idle.staleLights(),[]);
 const last=makeBaker(ctx,server,list,{round:2,force:true,owner:'last'});await last.bakeNext();
 const pending=server.manifests.get(ctx.atlas.key).forceRound;
 assert.equal(await idle.settle(),false,'settle follows the server force before declaring completion');
 assert.equal(server.manifests.get(ctx.atlas.key).forceRound,pending);assert.ok(pending);
 assert.equal(server.manifests.get(ctx.atlas.key).complete,false);
 await bakeAll(last);assert.equal(server.manifests.get(ctx.atlas.key).forceRound,undefined);
 assert.equal(server.lease.overlaps,0);
});
await check('fix4_force_start_preserves_current_ownership',async()=>{
 const ctx=await setup(),server=fakeServer({leaseRequired:true}),list=[k1,k2,h1,c1];
 await bakeAll(makeBaker(ctx,server,list));
 const before=structuredClone(server.manifests.get(ctx.atlas.key));let start=null;
 const api=async(path,init)=>{
   if(init?.method==='PUT'){
     const next=JSON.parse(init.body);
     if(next.forceRound&&!start)start=structuredClone(next);
   }
   return server.api(path,init);
 };
 const force=B.createBaker(ctx.view,{renderer:ctx.renderer,atlas:ctx.atlas,layout:ctx.layout,
   lights:[...list,k3],codec,force:true,owner:'late',api});
 await force.staleLights();
 // A second desk publishes a real new contributor after this force's first read.
 await bakeAll(makeBaker(ctx,server,[...list,k3],{owner:'other'}));
 const latest=structuredClone(server.manifests.get(ctx.atlas.key));
 assert.notDeepEqual(before.ownership,latest.ownership,'fixture changed stored ownership');
 await force.bakeNext();
 assert.ok(start);assert.deepEqual(start.ownership,latest.ownership,'start PUT uses the lease-protected read');
});
await check('fix2_panel_refresh_error_does_not_stop_poll',async()=>{
 const seed=await context('high',null,null,{poll:0});let panel;
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');seed.controller.stop();
   const server=seed.server,key=seed.controller.state().key,m=server.manifests.get(key),saved=structuredClone(m.lights.c1);
   delete m.lights.c1;let broken=false,thrown=false;
   location.search='?panel=true';
   panel=await context('low',server,null,{poll:100,host:new Node('div'),api:(path,init,next)=>{
     if(broken&&!thrown&&path===`api/house/bakes/${key}`){thrown=true;throw new Error('one panel refresh failure');}
     return next(path,init);
   }});location.search='';
   await until(()=>panel.controller.fresh().length===3,'partial panel');broken=true;
   await until(()=>!!panel.controller.state().error,'panel reports failure');
   m.lights.c1=saved;
   await until(()=>panel.controller.fresh().length===4&&!panel.controller.state().error,'next publication loads on poll');
   assert.equal(buttonsOf(panel).length,0);assert.equal(panel.renderer.log.renders,0);
 }finally{location.search='';seed.controller.stop();panel?.controller.stop();}
});
await check('fix2_overflow_recovers_after_lights_are_removed',async()=>{
 let list=[k1,k2,h1,c1];const view={live:{layout:()=>liveLayout(list),refresh:async()=>{}}};
 const desk=await context('high',null,null,{view,maxArrayLayers:1,poll:50,host:new Node('div')});
 try{
   await until(()=>!!desk.controller.state().error,'overflow');
   assert.equal(buttonsOf(desk)[1].hidden,true,'Resume cannot solve a GPU layer limit');
   assert.match(outputOf(desk).textContent,/Using real-time lighting/);
   list=[];
   await until(()=>!!desk.controller.held()&&!desk.controller.state().error,'poll prepares a smaller layout');
   assert.equal(desk.controller.packing().layers.flat().length,0);
 }finally{desk.controller.stop();}
});
await check('fix2_readonly_and_child_401_recover_without_resume',async()=>{
 const seed=await context('high',null,null,{poll:0});
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');seed.controller.stop();
   for(const tier of ['low','high']){
     let expired=false;
     const reader=await context(tier,seed.server,null,{deny:tier==='high',poll:50,host:new Node('div'),api:(path,init,next)=>
       expired&&path.includes('/bakes/')?Promise.resolve(new Response('',{status:401})):next(path,init)});
     try{
       await until(()=>reader.controller.fresh().length===4,'reader loads');expired=true;
       await until(()=>!!reader.controller.state().error,'read 401 visible');
       assert.equal(reader.controller.state().paused,false);assert.equal(reader.controller.state().retryAt,null);
       assert.equal(buttonsOf(reader).length,0,'readers have no actions');
       assert.equal(outputOf(reader),undefined,'read errors remain silent on non-bake views');
       assert.equal(reader.host.children.length,0,'no empty Lighting strip');
       expired=false;
       await until(()=>!reader.controller.state().error,'normal poll recovers');
       assert.equal(reader.controller.fresh().length,4);assert.equal(reader.renderer.log.renders,0);
     }finally{reader.controller.stop();}
   }
 }finally{seed.controller.stop();}
});
await check('fix3_renewal_blips_only_abort_after_expiry_or_lost_lease',async()=>{
 const nativeSet=setInterval,nativeClear=clearInterval,now=Date.now;
 let tick,offset=0,renewCount=0,mode='blips';
 globalThis.setInterval=(fn,ms)=>{assert.equal(ms,20000);tick=fn;return {};};globalThis.clearInterval=()=>{};
 Date.now=()=>now()+offset;
 const api=async(path,init)=>{
   const {action}=JSON.parse(init.body);
   if(action==='release')return new Response('{}');
   renewCount++;
   if(renewCount===1)return new Response('{"held":true}');
   if(mode==='blips'&&renewCount===2)throw new TypeError('one offline renew');
   if(mode==='blips'&&renewCount===3)return new Response('',{status:503});
   if(mode==='401')return new Response('',{status:401});
   if(mode==='409')return new Response('',{status:409});
   if(mode==='other')return new Response('{"held":false}');
   if(mode==='expired')return new Response('',{status:503});
   return new Response('{"held":true}');
 };
 try{
   const value=await withBakeLease(api,'key','owner',()=>true,async check=>{
     offset=10000;tick();await check();
     offset=20000;tick();await check();
     offset=30000;tick();await check();
     offset=60000;await check(); // successful renew reset the expiry clock
     return 'finished';
   });assert.equal(value,'finished');
   for(const fatal of ['401','409','other','expired']){
     mode=fatal;renewCount=0;offset=0;
     await assert.rejects(withBakeLease(api,'key','owner',()=>true,async check=>{
       offset=fatal==='expired'?40001:20000;tick();await check();return 'must not finish';
     }),fatal==='expired'?/HTTP 503/:/HTTP (401|409)/);
   }
 }finally{globalThis.setInterval=nativeSet;globalThis.clearInterval=nativeClear;Date.now=now;}
});
await check('fix5_successful_run_clears_concurrent_poll_error',async()=>{
 const nativeSet=globalThis.setTimeout,parked=[];
 let throwPoll=false,thrown=false;
 // After the failing poll, park later polls so only the run can clear its error.
 globalThis.setTimeout=(fn,ms,...args)=>{
   if(fn.name==='tick'&&thrown){const id=nativeSet(()=>{},100000);parked.push(id);return id;}
   return nativeSet(fn,ms,...args);
 };
 const view={live:{layout:()=>{
   if(throwPoll&&!thrown){thrown=true;throw new Error('concurrent poll broke');}
   return liveLayout([k1,k2,h1,c1]);
 },refresh:async()=>{}}};
 const desk=await context('high',null,null,{view,poll:50,host:new Node('div')});
 try{
   await until(()=>desk.controller.state().baking,'run starts');throwPoll=true;
   await until(()=>thrown&&!!desk.controller.state().error,'poll error occurs during run');
   await until(()=>desk.controller.state().done===4&&!desk.controller.state().baking,'same run finishes');
   assert.equal(desk.controller.state().error,null);assert.equal(desk.controller.state().retryAt,null);
   assert.equal(buttonsOf(desk)[1].hidden,true);assert.equal(outputOf(desk).hidden,true);
 }finally{desk.controller.stop();globalThis.setTimeout=nativeSet;parked.forEach(clearTimeout);}
});
await check('fix5_force_reload_first_progress_is_manifest_progress_and_copy_wraps',async()=>{
 const seed=await context('high',null,null,{poll:0});let reopened;
 const descriptor=Object.getOwnPropertyDescriptor(Node.prototype,'textContent'),messages=[];
 try{
   await until(()=>seed.controller.state().done===4&&!seed.controller.state().baking,'seed');
   const server=seed.server,key=seed.controller.state().key;let failed=false;
   server.fail=(method,path)=>{
     const m=server.manifests.get(key);
     if(!failed&&method==='POST'&&path.endsWith('.png')&&m.forceRound&&Object.values(m.lights).filter(e=>e.forceRound===m.forceRound).length===2){failed=true;return 500;}
   };
   await seed.controller.now();seed.controller.stop();server.fail=null;
   Object.defineProperty(Node.prototype,'textContent',{...descriptor,set(value){
     if(this.tagName==='OUTPUT'&&String(value).startsWith('Baking lights'))messages.push(String(value));
     descriptor.set.call(this,value);
   }});
   reopened=await context('high',server,null,{poll:0,host:new Node('div')});
   await until(()=>reopened.controller.state().done===4&&!reopened.controller.state().baking,'reload continues');
   assert.equal(messages[0],'Baking lights 2 of 4','no misleading 4 of 4 before manifest is read');
   assert.deepEqual(reopened.controller.state().baked,['h1','c1']);
   const template=readFileSync(job.root+'/static/twin/editor/editor.css','utf8');
   const rule=template.match(/#twin-bake-controls\s*\{([^}]+)\}/)[1];
   assert.match(rule,/white-space:normal/);assert.match(rule,/overflow-wrap:anywhere/);assert.match(rule,/min-width:0/);
   const live=readFileSync(job.root+'/tests/test_house_twin_bake_live.py','utf8');
   assert.ok(!live.includes('0, 0 when idle'));assert.ok(live.includes('retained when idle'));
 }finally{Object.defineProperty(Node.prototype,'textContent',descriptor);seed.controller.stop();reopened?.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""

if __name__ == '__main__':
    R.DRIVER = DRIVER
    sys.exit(R.run())
