"""Run the idle lifecycle on the real mounted twin with a stub renderer."""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {mountIdle} = await import(file('static/twin/live/idle.js'));
globalThis.Renderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
let view, idle, trigger, current=0, clocks=0, heroes=0, updates=0;
const realDateNow=Date.now;let wallNow=realDateNow();Date.now=()=>wallNow;
const realTimeout=globalThis.setTimeout, realClear=globalThis.clearTimeout;
globalThis.setTimeout=(fn,ms)=>ms===1234?(trigger=fn,991):realTimeout(fn,ms);
globalThis.clearTimeout=id=>id===991?undefined:realClear(id);
const bar=document.getElementById('twin-glance'), home=document.getElementById('twin-glance-home'), card=document.getElementById('twin-idle-clock');
const root=document.getElementById('twin-idle');root.hidden=true;home.append(bar);
const glance={move:parent=>parent.append(bar)};
let saved;
await test('desk defaults off and panel opt-in arms the idle timer',async()=>{
  view=await mountTwin(new Element(),{plan:input.plan,kit:{materials:{}},tier:'low',bake:false});
  view.live={draw(){},peek:()=>({'weather.home':{state:'sunny',attributes:{temperature:70,temperature_unit:'°F'}}}),stale:()=>false,closeRoom(){},stop(){}};
  idle=mountIdle(view,glance,{timeout:1234,now:()=>current,clock:()=>clocks++,hero:{html:(_next,options)=>{assert.equal(options.compact,true);heroes++;return'';}},
    api:async()=>({ok:true,json:async()=>({hero:{next:{title:'Next',end:'2099-01-01T12:00:00Z'}}})})});
  view.idle=idle;
  assert.equal(trigger,undefined);assert.equal(idle.active(),false);
  idle.configure(true);assert.equal(typeof trigger,'function');
});
await test('enter captures orthographic floor camera and moves one bar',async()=>{
  view.levels.go({building:input.plan.buildings[0].id,floor:input.plan.buildings[0].levels[0].id},{immediate:true});view.setTime('day');
  saved=view.saveView();trigger();await Promise.resolve();await Promise.resolve();
  assert.equal(idle.active(),true);assert.equal(root.hidden,false);assert.equal(view.state.view,'ext');
  assert.equal(view.state.time,'now');assert.equal(bar.parentElement,card);assert.equal(view.controls.enabled,false);
  assert.equal(document.querySelectorAll('#twin-glance').length,1);assert.ok(clocks>0);
  assert.notEqual(document.documentElement.getAttribute('data-twin-idle'),null,'idle applies the scene-over-Argyle stacking scope');
});
await test('slow orbit emits no human camera change and retains live sun',()=>{
  view.controls.addEventListener('change',()=>updates++);
  const before=view.camera.position.clone(),sun=view.scene.getObjectByName('real-sun');
  let controlsCalls=0;const original=view.controls.update;
  view.controls.update=()=>{controlsCalls++;original.call(view.controls);};
  current=10000;wallNow+=1000;view.renderer3.loop(current);assert.ok(before.distanceTo(view.camera.position)>0);
  assert.equal(controlsCalls,0,'idle animation never runs OrbitControls.update, so it cannot starve the baker');
  view.controls.update=original;
  assert.equal(updates,0);assert.equal(view.scene.getObjectByName('real-sun'),sun);
  assert.match(document.getElementById('twin-idle-weather').textContent,/70 °F/);
  assert.ok(heroes>0,'the shared compact hero builder is called');assert.equal(document.getElementById('twin-idle-next').hidden,false);
});
await test('wake restores exact view position quaternion target zoom and preview',()=>{
  idle.wake();assert.equal(root.hidden,true);assert.equal(bar.parentElement,home);
  assert.equal(document.documentElement.getAttribute('data-twin-idle'),null,'wake restores the original Argyle stacking');
  assert.equal(view.camera,saved.camera);assert.deepEqual(view.camera.position.toArray(),saved.position.toArray());
  assert.deepEqual(view.camera.quaternion.toArray(),saved.quaternion.toArray());
  assert.deepEqual(view.controls.target.toArray(),saved.target.toArray());assert.equal(view.camera.zoom,saved.zoom);
  assert.deepEqual(view.state,saved.state);assert.deepEqual(view.levels.save(),saved.navigation);assert.equal(view.controls.enabled,true);
});
await test('idle orbit and wake preserve a floor pin at exterior distance in Day and Night',()=>{
  try {
    for(const preview of ['day','night']) {
      const floor=view.levelKeys()[0];
      view.levels.go({building:input.plan.buildings[0].id,floor:input.plan.buildings[0].levels[0].id},{immediate:true});view.setTime(preview);
      view.camera.position.x+=2;view.controls.target.x+=2;view.camera.zoom=1.7;
      view.controls.update();view.render();
      assert.equal(view.viewingState().pinned,floor,'the saved floor is pinned');
      const before=view.saveView();
      trigger();assert.equal(idle.active(),true);
      const orbitStart=view.camera.position.clone();
      for(const elapsed of [10000,60000,180000]) {
        current+=elapsed;idle.frame(current);view.render();
        assert.equal(view.state.view,'ext','the idle orbit uses the exterior');
      }
      assert.ok(orbitStart.distanceTo(view.camera.position)>0,'the idle camera actually orbits');
      idle.wake();
      assert.equal(view.viewingState().pinned,floor,'wake restores the floor pin');
      assert.equal(view.viewingState().selected,floor);
      assert.deepEqual(view.state,before.state);assert.deepEqual(view.levels.save(),before.navigation);
      assert.equal(view.camera,before.camera);
      assert.deepEqual(view.camera.position.toArray(),before.position.toArray());
      assert.deepEqual(view.camera.quaternion.toArray(),before.quaternion.toArray());
      assert.deepEqual(view.controls.target.toArray(),before.target.toArray());
      assert.equal(view.camera.zoom,before.zoom);
      view.renderer3.loop(++current);
      assert.equal(view.viewingState().pinned,floor,'the next frame keeps the restored pin');
      assert.equal(view.state.view,floor);
      // Distance alone cannot release an explicit viewer floor. The gesture
      // threshold is evaluated by the level owner when the zoom ends.
      view.camera.position.copy(before.target).add(before.position.clone().sub(before.target).multiplyScalar(1.26));view.render();
      assert.equal(view.viewingState().pinned,floor);
      assert.equal(view.levels.zoomEnd(1.24),'spring');view.cancelCameraMotion();
      assert.equal(view.viewingState().pinned,floor);
      assert.equal(view.levels.zoomEnd(1.5),'up');view.cancelCameraMotion();
      assert.equal(view.viewingState().pinned,null);assert.equal(view.state.view,'ext');
    }
  } finally {idle.wake();view.restoreView(saved);view.setTime(saved.state.time);}
});
await test('idle restores Room and Building navigation including fitted zoom distance',()=>{
  const b=input.plan.buildings[0];
  for(const next of [{building:b.id,room:b.rooms[0].id},{building:b.id}]) {
    view.levels.go(next,{immediate:true});const before=view.saveView();
    trigger();assert.equal(view.levels.snapshot().level,'house');
    current+=10000;idle.frame(current);idle.wake();
    assert.deepEqual(view.levels.save(),before.navigation);
    assert.deepEqual(view.camera.position.toArray(),before.position.toArray());
    assert.deepEqual(view.controls.target.toArray(),before.target.toArray());
  }
  view.restoreView(saved);
});
await test('pointer move touch and key each wake through the installed listener',async()=>{
  for(const name of ['pointermove','pointerdown','touchstart','keydown']) {
    trigger();assert.equal(idle.active(),true);const event=await fire(window,name,{key:'Escape'});
    assert.equal(idle.active(),false,name);assert.equal(event.defaultPrevented,true);
    assert.deepEqual(view.camera.position.toArray(),saved.position.toArray());
  }
});
await test('periodic preferences refresh does not reset one-minute idle clock',()=>{
  const first=trigger;idle.configure(true);assert.equal(trigger,first);
  idle.configure(false);assert.equal(idle.active(),false);assert.equal(window._chfTwinIdleEnabled,false);
  idle.configure(true);trigger();assert.equal(idle.active(),true);idle.stop();assert.equal(idle.active(),false);
  assert.equal(window._chfTwinIdleEnabled,false);assert.equal(bar.parentElement,home);
});
view?.dispose();globalThis.setTimeout=realTimeout;globalThis.clearTimeout=realClear;Date.now=realDateNow;
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    for index, room in enumerate(plan['buildings'][0]['rooms']):
        room.setdefault('id', 'room-' + str(index))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
