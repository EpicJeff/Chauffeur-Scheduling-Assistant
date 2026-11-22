"""Two bakers sharing one server cannot republish a stale legacy channel."""
import sys
import test_twin_baker_js as B

DRIVER = B.DRIVER[:B.DRIVER.index('const checks = [];')] + r"""
const checks=[];const check=(name,fn)=>checks.push([name,fn]);
const list=[k1,k2,h1,c1];
async function legacy(){
 const ctx=await setup(),server=fakeServer({leaseRequired:true}),initial=makeBaker(ctx,server,list);
 await bakeAll(initial);await initial.settle();
 const m=server.manifests.get(ctx.atlas.key);delete m.pageIntegrity;
 for(const e of Object.values(m.lights))delete e.cheap;
 return {ctx,server,m};
}
check('bake_step_keeps_another_desks_new_page_and_integrity_receipt',async()=>{
 const {ctx,server,m}=await legacy(),key=ctx.atlas.key;
 m.lights.k1.key='0'.repeat(32);m.lights.c1.key='0'.repeat(32);
 const a=makeBaker(ctx,server,list,{inspectLegacy:true,owner:'desk-a'}),b=makeBaker(ctx,server,list,{inspectLegacy:true,owner:'desk-b'});
 await Promise.all([a.staleLights(),b.staleLights()]);
 FILL.value=.24;assert.equal(await a.bakeNext(),'k1');
 const page=server.manifests.get(key).lights.k1.pages.find(p=>!m.lights.c1.pages.includes(p));
 assert.notEqual(page,undefined,'fixture has a page the second light does not write');
 const receipt=structuredClone(server.manifests.get(key).pageIntegrity[page]),bytes=server.pages.get(key+'/'+page).slice(),since=server.calls.length;
 FILL.value=.4;assert.equal(await b.bakeNext(),'c1');await b.settle();
 assert.deepEqual(server.pages.get(key+'/'+page),bytes,'the first desk channel survives legacy migration');
 assert.deepEqual(server.manifests.get(key).pageIntegrity[page],receipt,'latest receipt survives publication');
 assert.ok(!server.writes(since).some(c=>c.path===`api/house/bakes/${key}/${page}.png`));
 assert.equal(server.lease.overlaps,0);assert.deepEqual(server.bad,[]);
});
check('settle_skips_pages_already_migrated_by_another_baker',async()=>{
 const {ctx,server}=await legacy(),key=ctx.atlas.key;
 const b=makeBaker(ctx,server,list,{inspectLegacy:true,owner:'desk-b'});assert.deepEqual(await b.staleLights(),[]);
 const a=makeBaker(ctx,server,list,{inspectLegacy:true,force:true,owner:'desk-a'});
 FILL.value=.32;await bakeAll(a);await a.settle();
 const before=structuredClone(server.manifests.get(key).pageIntegrity),pages=new Map(server.pages),since=server.calls.length;
 await b.settle();
 assert.deepEqual(server.manifests.get(key).pageIntegrity,before);assert.deepEqual(server.pages,pages);
 assert.equal(server.writes(since).filter(c=>c.path.endsWith('.png')).length,0);
});
check('etag_change_without_a_manifest_receipt_also_blocks_stale_legacy_upload',async()=>{
 const {ctx,server,m}=await legacy(),key=ctx.atlas.key;
 const b=makeBaker(ctx,server,list,{inspectLegacy:true,owner:'desk-b'});assert.deepEqual(await b.staleLights(),[]);
 const page=m.lights.k1.page,old=server.pages.get(key+'/'+page);
 const bytes=await codec.encode({width:256,height:256,channels:[new Uint8Array(256*256).fill(90),new Uint8Array(256*256).fill(120)]});
 assert.notDeepEqual(old,bytes);
 const {withBakeLease}=await import(file('static/twin/bake/bake_lock.js'));
 await withBakeLease(server.api,`api/house/bakes/${key}`,'desk-a',()=>true,async()=>{
  const r=await server.api(`api/house/bakes/${key}/${page}.png`,{method:'POST',headers:{'X-Bake-Owner':'desk-a'},body:bytes});assert.ok(r.ok);
  // A page upload can finish before a failed manifest PUT. No receipt exists.
 });
 const since=server.calls.length;await b.settle();
 assert.deepEqual(server.pages.get(key+'/'+page),bytes);
 assert.ok(!server.writes(since).some(c=>c.path===`api/house/bakes/${key}/${page}.png`));
 assert.equal(server.manifests.get(key).pageIntegrity[page],undefined,'never sign bytes this desk did not inspect');
});
""" + B.DRIVER[B.DRIVER.index('const only = process.argv[3]'):]

if __name__ == '__main__':
    B.DRIVER=DRIVER
    sys.exit(B.run(sys.argv[1] if len(sys.argv)>1 else None))
