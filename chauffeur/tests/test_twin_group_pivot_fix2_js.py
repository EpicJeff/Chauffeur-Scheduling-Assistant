"""Real-yard group pivots after history undo and a deferred foreign save.

Run from chauffeur/: python tests/test_twin_group_pivot_fix2_js.py.
The renderer and external tree generator are doubled; buildYard, rendered
plant ownership/bounds, settle, history and the gizmo execute normally.
"""
import json
from pathlib import Path
import sys

from twin_editor_dom import run_node
from test_twin_view_settle_js import PREFIX

ROOT = Path(__file__).resolve().parents[1]

# An optional in-memory baseline lets the regression prove the pre-fix failure
# without changing production files or checking out another tree.
PREFIX = PREFIX.replace("load(url, ctx, next) {", """load(url, ctx, next) {
  const baseline = input.baselineSources?.[url];
  if (baseline !== undefined) return {format:'module',source:baseline,shortCircuit:true};""")

DRIVER = PREFIX + r"""
globalThis.__THREE_MESH=T.Mesh;globalThis.__THREE_BOX=T.BoxGeometry;globalThis.__THREE_STD=T.MeshStandardMaterial;
// The full household includes reflective water; retain the renderer rig's
// normal no-WebGL behavior while supplying its viewport bookkeeping methods.
Object.assign(globalThis.Renderer.prototype,{
 getDrawingBufferSize(v){return this.getSize(v).multiplyScalar(this.getPixelRatio());},
 getViewport(v){return v.set(0,0,this.size.x,this.size.y);},setViewport(){},
 getScissor(v){return v.set(0,0,this.size.x,this.size.y);},setScissor(){},
 getScissorTest(){return false;},setScissorTest(){}
});
const {createGizmo}=await import(file('static/twin/editor/gizmo.js'));
const {createHistory}=await import(file('static/twin/editor/history.js'));
const FT=.3048;
const near=(actual,wanted,label)=>assert.ok(Math.abs(actual-wanted)<1e-6,`${label}: ${actual} near ${wanted}`);
const waitFor=async(predicate,label)=>{
 for(let i=0;i<150&&!predicate();i++)await new Promise(r=>setTimeout(r,5));
 assert.ok(predicate(),label);
};
const yard=v=>v.scene.getObjectByName('yard');
function boundsCentre(v,refs){
 const ids=new Set(refs.map(r=>r.pieceId));
 const rows=v.selectionWorldBounds().filter(r=>!r.buildingId&&ids.has(r.pieceId));
 assert.equal(rows.length,30,'every selected plant has real rendered ownership bounds');
 const union=new T.Box3();
 for(const row of rows){
  const size=row.box.getSize(new T.Vector3());
  assert.ok(size.x>0&&size.y>0&&size.z>0,'rendered plant mesh bounds, not fallback points');
  union.union(row.box);
 }
 const p=union.getCenter(new T.Vector3());return [p.x/FT,-p.z/FT,p.y/FT];
}
function pointEvent(v,p){
 const q=new T.Vector3(p[0]*FT,p[2]*FT,-p[1]*FT).project(v.camera),rect=v.renderer3.domElement.getBoundingClientRect();
 return {clientX:rect.left+(q.x+1)*rect.width/2,clientY:rect.top+(1-q.y)*rect.height/2,button:0};
}
async function exercise(foreign){
 globalThis.generations=0;globalThis.bakeStarts=0;globalThis.yardCalls=0;
 location.search='?test=1';
 const plan=structuredClone(input.plan);
 plan.site.planting=plan.site.planting.filter(p=>p.state!=='ghost'&&p.at&&p.preset&&p.height>0).slice(0,30);
 assert.equal(plan.site.planting.length,30,'real household supplies the selected plants');
 const refs=plan.site.planting.map(p=>({kind:'planting',pieceId:p.id}));
 const shell=new Element();shell.className='editor-shell';const host=new Element();shell.append(host);document.body.append(shell);
 const view=await mountTwin(host,{plan,kit:input.kit,tier:'high',bake:false});
 const life=new AbortController(),layer=new Element();host.append(layer);
 let gizmo,unblock,round=1,refreshDone=false,restoredResult=null,sends=[];
 const oldFetch=globalThis.fetch;
 try{
  const plantObjects=[];yard(view).traverse(o=>{if(o.userData.kind==='planting'&&refs.some(r=>r.pieceId===o.userData.pieceId))plantObjects.push(o);});
  assert.equal(new Set(plantObjects.map(o=>o.userData.pieceId)).size,30,'real buildYard plant meshes exist');
  const original=structuredClone(view.plan),initial=boundsCentre(view,refs);
  view.camera.position.set(initial[0]*FT,initial[2]*FT+200,-initial[1]*FT+.01);
  view.camera.lookAt(initial[0]*FT,initial[2]*FT,-initial[1]*FT);view.camera.updateMatrixWorld(true);
  let boundsReads=0;
  const worldBounds=view.selectionWorldBounds.bind(view);
  view.selectionWorldBounds=()=>{boundsReads++;return worldBounds();};
  gizmo=createGizmo({view,layer,getPlan:()=>view.plan,getSelection:()=>({kind:'planting',id:refs.at(-1).pieceId}),getMembers:()=>refs,
   getTool:()=> 'rotate',op:()=>assert.fail('group turn must be one batch'),applyBatch:async ops=>sends.push(ops)});
  // This is the production scene-tools subscription, including the view's
  // deferred-yard -> controls-change notification.
  view.controls.addEventListener('change',gizmo.draw);
  const history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,signal:life.signal,
   latest:async()=>{},refresh:async()=>{restoredResult=await view.settle(structuredClone(original));gizmo.draw();refreshDone=true;}});
  const moved=structuredClone(original);
  for(const p of moved.site.planting){p.at[0]+=12;p.at[1]-=7;}
  const oldYard=yard(view);
  await history.perform(async()=>{await view.settle(moved);round=2;});
  await waitFor(()=>yard(view)!==oldYard&&!view.yardSettling,'earlier move yard has landed');
  const movedCentre=boundsCentre(view,refs);
  near(movedCentre[0],initial[0]+12,'move rendered east');near(movedCentre[1],initial[1]-7,'move rendered north');
  let handle=gizmo.handles()[0];assert.ok(handle,'Rotate group handle mounted');
  near(handle.centre[0],movedCentre[0],'moved group centre');
  const movedYard=yard(view),callsBefore=globalThis.yardCalls;
  globalThis.yardGate=new Promise(resolve=>unblock=resolve);
  if(foreign){
   restoredResult=await view.settle(structuredClone(original));gizmo.draw();refreshDone=true;round=3;
  }else{
   let revertCalls=0;
   globalThis.fetch=async(url,options)=>{
    assert.ok(url.endsWith('api/house/twin/revert'),'real history calls the revert route');
    assert.equal(JSON.parse(options.body).round,1);revertCalls++;round=3;
    return {ok:true,status:200,text:async()=>JSON.stringify({round:3})};
   };
   await fire(document.getElementById('rail-undo'),'click');
   await waitFor(()=>refreshDone,'production history undo refreshed the restored plan');
   assert.equal(revertCalls,1,'one undo request');
  }
  assert.equal(restoredResult.path,'deform','yard-only undo/foreign save uses real deform path');
  await waitFor(()=>globalThis.yardCalls>callsBefore,'restored yard build entered its gate');
  assert.equal(yard(view),movedYard,'old rendered yard remains until asynchronous swap');
  const restoredPlanIdentity=view.plan;
  // Intentionally cache the restored-plan record while only the old moved
  // yard is rendered: this is the stale-pivot failure's timing window.
  handle=gizmo.handles()[0];near(handle.centre[0],movedCentre[0],'interim rendered centre');
  const readsBeforeLand=boundsReads;
  globalThis.yardGate=null;unblock();unblock=null;
  await waitFor(()=>yard(view)!==movedYard&&!view.yardSettling,'restored yard swap completed');
  assert.equal(view.plan,restoredPlanIdentity,'yard swap keeps authoritative plan identity');
  const redrewOnLanding=boundsReads>readsBeforeLand;
  const restored=boundsCentre(view,refs);
  for(let i=0;i<3;i++)near(restored[i],initial[i],`restored rendered bounds axis${i}`);
  handle=gizmo.handles()[0];
  for(let i=0;i<3;i++)near(handle.centre[i],restored[i],`restored gizmo pivot axis${i}`);
  assert.ok(redrewOnLanding,'yard completion redraws group without a camera/input event');
  assert.ok(Math.hypot(handle.centre[0]-movedCentre[0],handle.centre[1]-movedCentre[1])>10,'pivot left the moved centre');
  assert.ok(gizmo.begin(pointEvent(view,handle.at),handle));await gizmo.commit(90);
  assert.equal(sends.length,1,'following typed turn sends one batch');
  const first=original.site.planting[0],move=sends[0].find(op=>op.op==='move_site_item'&&op.id===first.id);
  assert.ok(move,'following turn relocates the first selected plant');
  near(move.at[0],restored[0]-(first.at[1]-restored[1]),'typed turn about restored east pivot');
  near(move.at[1],restored[1]+(first.at[0]-restored[0]),'typed turn about restored north pivot');
 }finally{
  globalThis.fetch=oldFetch;globalThis.yardGate=null;unblock?.();life.abort();
  if(gizmo){view.controls.removeEventListener('change',gizmo.draw);await gizmo.finish(true);}
  view.dispose();shell.remove();
 }
}
await test('real_30_plant_pivot_after_history_undo',()=>exercise(false));
await test('real_30_plant_pivot_after_foreign_save',()=>exercise(true));
finish();
"""


def payload():
    sys.path.insert(0, str(ROOT))
    from services.twin_model_bridge import assemble, flatten
    raw = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'))
    kit['manifest'] = {}
    return {'root': ROOT.as_posix(), 'plan': flatten(assemble(raw)[0]), 'kit': kit}


if __name__ == '__main__':
    data = payload()
    if '--baseline' in sys.argv:
        import subprocess
        data['baselineSources'] = {}
        for name in ('gizmo.js', '../twin_view.js'):
            path = (ROOT / 'static/twin/editor' / name).resolve()
            relative = path.relative_to(ROOT.parent).as_posix()
            source = subprocess.run(['git', 'show', 'HEAD:' + relative], cwd=ROOT.parent,
                                    capture_output=True, text=True, encoding='utf8', check=True).stdout
            data['baselineSources'][path.as_uri()] = source
    code, output = run_node(DRIVER, data, timeout=180)
    print(output)
    sys.exit(code or 0)
