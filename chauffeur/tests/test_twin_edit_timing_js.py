"""Execute the actual editor/API/menu and actual view/generator under Node."""
import json
from pathlib import Path
import re
import sys
from twin_live_node_rig import run
from twin_editor_dom import run_node
from test_twin_yard_reuse_js import PREFIX
from test_twin_editor_history_js import DRIVER as HISTORY_DRIVER, STUBS

ROOT = Path(__file__).resolve().parents[1]

# Reuse the history rig's real editor boot and transport fixtures, then test
# timing through its public op hook. The renderer is tested separately below.
EDITOR = HISTORY_DRIVER.split(' const zoneResize=')[0].replace(
    "const response=(status,body)=>({ok:status<400,status,text:async()=>JSON.stringify(body)});",
    "const response=(status,body)=>({ok:status<400,status,headers:{get:()=> 'lock;dur=1.2, apply;dur=2.3'},text:async()=>{await wait(2);return JSON.stringify({...body,timing:{apply:2.3},bytes:123});}});") + r"""
 const stored=new Map();globalThis.localStorage={getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)};
 const overlay=document.getElementById('editor-edit-timing'),toggle=document.getElementById('menu-edit-timing');
 assert.equal(overlay.hidden,true);
 // Hold the observed frame after render, independently of the state refresh.
 const frameGate=deferred();let frames=0;
 editorView.afterNextRender=async()=>{frames++;await frameGate.promise;return {meshes:42,draw_calls:7,triangles:100};};
 await hooks.op({op:'resize_opening',building:'b',id:'door',width:4});
 assert.equal(frames,1);assert.equal(window.__twinEditTiming.length,0);
 frameGate.resolve();await until(()=>window.__twinEditTiming.length===1);
 let timing=window.__twinEditTiming[0];
 for(const name of ['request','parse','rebuild','first_frame','total','refresh_state'])assert.ok(Number.isFinite(timing[name])&&timing[name]>=0,name);
 assert.ok(timing.parse>=1);
 assert.ok(timing.total+1>=timing.request+timing.parse+timing.rebuild+timing.first_frame);
 assert.deepEqual(timing.server,{lock:1.2,apply:2.3});assert.equal(timing.bytes,123);
 assert.deepEqual(timing.counts,{meshes:42,draw_calls:7,triangles:100,buildings:0,levels:0});
 assert.deepEqual(JSON.parse(JSON.stringify(timing)),timing);
 ok('real applyOp records request, parse, rebuild, rendered frame, total, server timings and counts');
 await press(toggle);assert.equal(overlay.hidden,false);assert.match(overlay.textContent,/Edit .* ms/);
 assert.equal(toggle.getAttribute('aria-pressed'),'true');assert.equal(stored.get('chf.editor.editTiming'),'true');
 await press(toggle);assert.equal(overlay.hidden,true);assert.equal(stored.get('chf.editor.editTiming'),'false');
 ok('menu toggle shows/hides the breakdown and persists locally');
 const {mountEditTiming}=await import(file('static/twin/edit_timing.js'));
 const secondToggle=document.createElement('button'),secondOverlay=document.createElement('aside');
 stored.set('chf.editor.editTiming','true');const abortMenu=new AbortController();
 mountEditTiming({toggle:secondToggle,overlay:secondOverlay,signal:abortMenu.signal});
 assert.equal(secondOverlay.hidden,false);abortMenu.abort();
 ok('saved toggle is restored by the real menu builder');
 for(let i=0;i<32;i++)await hooks.op({op:'resize_opening',building:'b',id:'door',width:5+i});
 await until(()=>window.__twinEditTiming.length===30);
 assert.equal(window.__twinEditTiming.length,30);
 ok('only the last thirty edits are retained');
 let posts=0,posted;const beforeSend=fetch;
 const sendGate=deferred();
 globalThis.fetch=window.fetch=async(url,init)=>{
  if(String(url).endsWith('api/house/twin/perf')){posts++;posted=JSON.parse(init.body);await sendGate.promise;return response(200,posted);}
  return beforeSend(url,init);
 };
 const send=document.getElementById('menu-send-timing');await press(send);await press(send);
 assert.equal(posts,1);assert.equal(posted.kind,'edit_timing');assert.equal(posted.records.length,30);
 sendGate.resolve();await until(()=>!send.disabled);
 ok('Send timing report uses the existing perf endpoint once while pending');
 assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
 window.dispatchEvent(new Event('pagehide'));
 console.log(`${passed}/${passed} edit timing editor checks passed`);process.exit(0);
}catch(error){console.error(error);process.exit(1);}
"""

VIEW = PREFIX + r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {beginEdit,observeEditFrame}=await import(file('static/twin/edit_timing.js'));
const baseRenderer=globalThis.Renderer;
const baseRender=baseRenderer.prototype.render;
baseRenderer.prototype.setAnimationLoop=function(fn){this.loop=fn;};
baseRenderer.prototype.render=function(scene){baseRender.call(this,scene);this.info.render.calls=17;this.info.render.triangles=1234;};
const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);
const view=await mountTwin(host,{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false});
try {
 await test('real rebuild attributes generation, material, batching, yard, disposal and bake stop',async()=>{
  const record=beginEdit({op:'set'}),plan=structuredClone(input.plan);plan.buildings[0].name='Timed house';
  // Exercise the actual yard build, rather than an unchanged-plan reuse.
  plan.site.lot[0][0] -= 1;
  await view.rebuild(plan,{timing:record});
  for(const name of ['generate','batch','yard','materials','dispose','bake_stop','assets'])assert.ok(Number.isFinite(record.detail[name])&&record.detail[name]>=0,name);
  assert.ok(record.detail.generate>0);assert.ok(record.detail.batch>0);assert.ok(record.detail.materials>0);
  assert.ok(record.detail.yard>0);assert.equal(record.yard_reused,false);
  assert.ok(record.detail.yard_terrain>0);assert.ok(record.detail.yard_hardscape>0);
  assert.equal(record.counts.buildings,plan.buildings.length);
  assert.equal(record.counts.levels,plan.buildings.reduce((n,b)=>n+b.levels.length,0));
  assert.equal(record.buildings[0].id,plan.buildings[0].id);
  assert.ok(record.buildings[0].generate>0);
  assert.ok(record.buildings[0].levels.some(l=>l.walls>0));
  assert.ok(record.buildings[0].levels.some(l=>l.floors>0));
  const frame=observeEditFrame(view,record);let done=false;frame.then(()=>done=true);
  await tick();assert.equal(done,false,'a rAF alone is not a rendered frame');
  view.renderer3.loop();await tick();await frame;
  assert.equal(record.counts.draw_calls,17);assert.equal(record.counts.triangles,1234);assert.ok(record.counts.meshes>0);
  assert.ok(record.first_frame>=0);assert.ok(record.total>=record.first_frame);
 });
 await test('preserveYard follows the same rebuild path and reports zero yard work',async()=>{
  const record=beginEdit({op:'set'});await view.rebuild(view.plan,{preserveYard:true,timing:record});
  assert.equal(record.detail.yard,0);assert.ok(record.detail.dispose>0);assert.equal(record.counts.buildings,input.plan.buildings.length);
  assert.equal(record.yard_reused,true);
 });
}finally{view.dispose();}
finish();
"""


if __name__ == '__main__':
    ids = sorted(set(re.findall(r'id="([\w-]+)"', (ROOT / 'templates/house_editor.html').read_text(encoding='utf-8'))) | {'piece-card', 'rail-undo', 'rail-redo'})
    result = run(EDITOR, {'stubs': STUBS, 'ids': ids}, timeout=45)
    if result:
        sys.exit(result)
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(VIEW, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
