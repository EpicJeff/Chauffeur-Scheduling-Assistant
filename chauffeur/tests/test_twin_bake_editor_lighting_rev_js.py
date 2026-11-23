"""Lighting-neutral saved rounds through the actual editor bake runtime."""
import sys
import test_twin_bake_runtime_js as R

DRIVER = R.DRIVER[:R.DRIVER.index('await check(')] + r"""
const output=d=>d.host.querySelectorAll('output')[0];
const opts=view=>({mode:'manual',display:false,poll:0,parent:true,host:new Node('div'),view});
const ready=d=>until(()=>/^Lighting /.test(output(d)?.textContent),'editor status');
async function seed(){const d=await context('high',null,null,opts({round:42,lighting:'baked'}));await ready(d);await d.controller.start();return d;}
await check('neutral_round_stays_current_and_press_renders_nothing',async()=>{
 const d=await seed();let next;
 try{
  assert.equal(d.server.manifests.get(d.controller.state().key).lighting,'baked');
  d.view.round=43;d.controller.syncBlocked();
  assert.match(output(d).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);assert.deepEqual(d.controller.state().stale,[]);
  next=await context('high',d.server,null,opts({round:43,lighting:'baked'}));await ready(next);
  assert.equal(output(next).textContent,'Lighting is up to date');assert.deepEqual(next.controller.state().stale,[]);
  assert.equal(next.controller.fresh().length,4);assert.equal(next.controller.packing(),null);
  const renders=next.renderer.log.renders;await next.controller.start();
  assert.equal(next.renderer.log.renders,renders);assert.equal(output(next).textContent,'Lighting is up to date');
  const m=d.server.manifests.get(next.controller.state().key);assert.equal(m.round,43);assert.equal(m.lighting,'baked');
 }finally{next?.controller.stop();d.controller.stop();}
});
await check('lighting_change_and_revert_sync_without_poll_or_atlas',async()=>{
 const d=await seed();
 try{
  d.view.round=43;d.view.lighting='changed';d.controller.syncBlocked();
  assert.equal(output(d).textContent,'Lighting out of date since your edits');assert.equal(d.controller.state().stale.length,4);
  d.view.round=44;d.view.lighting='baked';d.controller.syncBlocked();
  assert.match(output(d).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);assert.deepEqual(d.controller.state().stale,[]);
  d.view.round=45;d.view.lighting='changed';await d.controller.refresh();
  assert.equal(output(d).textContent,'Lighting out of date since your edits');
  const renders=d.renderer.log.renders;await d.controller.start();
  assert.equal(d.renderer.log.renders,renders,'unchanged exact keys settle without rendering');
  assert.equal(d.server.manifests.get(d.controller.state().key).lighting,'changed');
  assert.match(output(d).textContent,/^Lighting is up to date · Grid \d+ points, \d+ KB$/);
 }finally{d.controller.stop();}
});
for(const missing of ['manifest','view'])await check('legacy_'+missing+'_keeps_round_fallback',async()=>{
 const d=await seed();let same,next;
 try{
  if(missing==='manifest')delete d.server.manifests.get(d.controller.state().key).lighting;
  same=await context('high',d.server,null,opts({round:42,...(missing==='view'?{}:{lighting:'baked'})}));await ready(same);
  assert.equal(output(same).textContent,'Lighting is up to date');
  next=await context('high',d.server,null,opts({round:43,...(missing==='view'?{}:{lighting:'baked'})}));await ready(next);
  assert.equal(output(next).textContent,'Lighting out of date since your edits');assert.equal(next.controller.state().stale.length,4);
  await next.controller.start();assert.equal(next.renderer.log.renders,0);
  assert.equal(output(next).textContent,'Lighting is up to date');
 }finally{same?.controller.stop();next?.controller.stop();d.controller.stop();}
});
await check('viewer_ignores_lighting_identity_and_editor_still_checks_light_moves',async()=>{
 const d=await seed();let viewer;
 try{
  viewer=await context('high',d.server,null,{mode:'readonly',parent:true,poll:0,host:new Node('div'),view:{round:43,lighting:'changed'}});
  await until(()=>!!viewer.controller.packing(),'viewer layout');await viewer.controller.refresh();
  assert.equal(viewer.controller.state().stale.length,0);assert.equal(viewer.controller.fresh().length,4);
  d.view.round=43;d.view.live={layout:()=>liveLayout([k1,k2,h1,{...c1,at:[c1.at[0]+1,c1.at[1],c1.at[2]]}])};
  await d.controller.refresh();assert.deepEqual(d.controller.state().stale,['c1']);
 }finally{viewer?.controller.stop();d.controller.stop();}
});
console.log(`${passed}/${ran} passed`);process.exit(passed===ran?0:1);
"""
if __name__ == '__main__':
    R.DRIVER = DRIVER
    sys.exit(R.run())
