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
  view.setView(view.levelKeys()[0]);view.setCamera('top');view.setTime('day');
  saved=view.saveView();trigger();await Promise.resolve();await Promise.resolve();
  assert.equal(idle.active(),true);assert.equal(root.hidden,false);assert.equal(view.state.view,'ext');
  assert.equal(view.state.time,'now');assert.equal(bar.parentElement,card);assert.equal(view.controls.enabled,false);
  assert.equal(document.querySelectorAll('#twin-glance').length,1);assert.ok(clocks>0);
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
  assert.match(document.getElementById('twin-idle-weather').textContent,/70°F/);
  assert.ok(heroes>0,'the shared compact hero builder is called');assert.equal(document.getElementById('twin-idle-next').hidden,false);
});
await test('wake restores exact view position quaternion target zoom and preview',()=>{
  idle.wake();assert.equal(root.hidden,true);assert.equal(bar.parentElement,home);
  assert.equal(view.camera,saved.camera);assert.deepEqual(view.camera.position.toArray(),saved.position.toArray());
  assert.deepEqual(view.camera.quaternion.toArray(),saved.quaternion.toArray());
  assert.deepEqual(view.controls.target.toArray(),saved.target.toArray());assert.equal(view.camera.zoom,saved.zoom);
  assert.deepEqual(view.state,saved.state);assert.equal(view.controls.enabled,true);
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
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
