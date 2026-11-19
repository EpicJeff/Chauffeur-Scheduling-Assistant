"""Queue integration through the real editor boot and request layer; no browser."""
from pathlib import Path
import re
import sys
from twin_live_node_rig import run
from test_twin_editor_history_js import DRIVER as HISTORY_DRIVER, STUBS

ROOT = Path(__file__).resolve().parents[1]
STUBS = STUBS.replace('return {select,selected:', 'return {clearDragFrame(){},select,selected:').replace('const cards=createCards', 'globalThis.sceneOptions=options;const cards=createCards').replace(
    'export const createDraw=()=>({cancel(){}});', 'export const createDraw=options=>(globalThis.drawOptions=options,{cancel(){}});').replace(
    'export const createTimeline=()=>({sync(){},preview:()=>null});', 'export const createTimeline=()=>({sync(){},preview:()=>null,now:async()=>{}});').replace(
    'export const createSteps=()=>({render(){}});', 'export const createSteps=()=>({render(){},close(){}});').replace(
    'export const createPlace=()=>({sync(){},isOpen:()=>false});',
    'export const createPlace=()=>({sync(sheets,state){globalThis.lastSnapshot=state;},isOpen:()=>false});')
DRIVER = HISTORY_DRIVER.split(' const zoneResize=')[0].replace(
    "['./api.js','./history.js','./lighting.js']",
    "['./api.js','./history.js','./lighting.js','./edit_queue.js','./local_ops.js']").replace(
    "const writes=[],reverts=[];", "const writes=[],reverts=[];let pollOverride=null,refuse=false,holdAnswer=null,answerReady=false,signOutStatus=null;").replace(
    "if(path==='editor/state')return response(200,state());",
    "if(path.startsWith('editor/state'))return response(200,pollOverride||state());if(path==='editor/start-over'){plan=null;rounds=[];seq=0;return response(200,{});}").replace(
    "if(op.op==='refuse')", "if(signOutStatus)return signOutStatus===401?{ok:false,status:401,text:async()=> 'Sign in'}:response(signOutStatus,{detail:'Sign in'});if(refuse||op.op==='refuse')").replace(
    "else assert.fail('unexpected mutation '+JSON.stringify(op));",
    "else if(['move_wall','set_object'].includes(op.op))plan=(await import(file('static/twin/editor/local_ops.js'))).applyLocal(plan,op).plan;else assert.fail('unexpected mutation '+JSON.stringify(op));").replace(
    "record();return response(200,{...state(),words:'Saved the change.',summary:'Saved the change.'});",
    "record();const answer={...state(),round:rounds.at(-1).id,words:'Saved the change.',summary:'Saved the change.'};if(holdAnswer){answerReady=true;await holdAnswer.promise;}return response(200,answer);") + r"""
 const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
 for(const id of ['houses-panel','cc-confirm-modal','cc-input-modal','cc-choice-modal']){
  const node=document.getElementById(id);if(node){node.hidden=true;node.classList.add('hidden');}
 }
 for(const name of ['alert','confirm','prompt'])globalThis[name]=window[name]=()=>{throw Error('Browser dialog: '+name);};
 plan.buildings[0].joints=[{id:'j1',level:'L1',at:[0,0]},{id:'j2',level:'L1',at:[10,0]}];
 plan.buildings[0].walls=[{id:'w',level:'L1',joints:['j1','j2'],from:[0,0],to:[10,0]}];
 plan.site.furniture=[{id:'chair',at:[0,0],scale:1}];
 saved.set(0,structuredClone(plan));
 window.dispatchEvent(new Event('focus'));await until(()=>sceneOptions.getPlan().buildings[0].walls.length===1);
 let rebuilds=[];const rebuild=editorView.rebuild;
 editorView.rebuild=async p=>{rebuilds.push(structuredClone(p));await rebuild(p);};
 const operation=config.case==='outline_object_settles'?{op:'set_object',list:'furniture',index:0,properties:{scale:2}}:{op:'move_wall',building:'b',wall:'w',by:1};
 const selection={pieceId:'w',buildingId:'b'};
 const local=applyLocal(plan,operation).plan;
 if(config.case==='dropped_dependencies_share_one_notice')local.buildings[0].walls.push({...local.buildings[0].walls[0],id:'dependent'});
 const gate=deferred();holdResponse=gate;
 let settles=[];
 if(config.case==='server_correction_remaps_selection'){
  window.__editor.clickPiece('w','b');editorView.plan=structuredClone(local);
  editorView.settle=async(p,info)=>{
   settles.push(info);editorView.plan=p;
   return {path:'rebuild',selection:{pieceId:'w-new',buildingId:'b',kind:'wall'}};
  };
 }
 if(config.case==='undo_refuses_over_foreign_round_after_replay')holdAnswer=deferred();
 let completed=false;
 const save=hooks.op(operation,{drag:true,...(config.case==='outline_object_settles'?{}:{local}),label:'Moving the wall',selection});
 save.then(()=>completed=true,()=>{});save.catch(()=>{});
 await until(()=>writes.length===1);
 if(config.case==='server_correction_remaps_selection'){
  // Force the accepted answer to differ from the held preview. The queue's
  // real onChange enters settleView(plan, {}) after replay.
  plan.buildings[0].rooms.push({id:'correction',level:'L1',polygon:[[0,0],[2,0],[0,2]]});
  gate.resolve();await save;await until(()=>settles.length===1);
  assert.equal(settles[0].buildingId,'b');assert.equal(settles[0].levelId,'L1');assert.equal(settles[0].touched,null);
  assert.deepEqual(settles[0].selection,{pieceId:'w',buildingId:'b'});
  assert.deepEqual(window.__editor.selected(),{pieceId:'w-new',buildingId:'b',kind:'wall'});
  assert.equal(rebuilds.length,0);
 }
 if(config.case==='outline_object_settles'){
  assert.equal(rebuilds.length,1,'outline-only object preview must settle before its answer');assert.equal(editorView.plan.site.furniture[0].scale,2);
  gate.resolve();await save;await wait(30);assert.equal(rebuilds.length,1,'equal answer retains the settled scene');assert.equal(editorView.plan.site.furniture[0].scale,2);
 }
 if(config.case==='kept_release_draws_once'){
  assert.equal(rebuilds.length,0);assert.equal(completed,false);
  assert.equal(document.getElementById('editor-save-state').textContent,'Saving 1 change');
  assert.deepEqual(sceneOptions.getPlan(),local);
  gate.resolve();await save;await wait(25);
  assert.equal(rebuilds.length,0);assert.equal(document.getElementById('editor-save-state').textContent,'Saved');
  window.dispatchEvent(new Event('focus'));await wait(30);assert.equal(rebuilds.length,0);
  assert.ok(Number.isFinite(window.__twinEditTiming.at(-1).settle));
 }
 if(config.case==='stale_poll_ignored'){
  seq=11;gate.resolve();await save;await wait(25);
  const before=structuredClone(lastSnapshot),count=rebuilds.length;
  pollOverride={...state(),current_round:11,rounds:[{id:11}],plan:{...plan,site:{stale:true}}};
  window.dispatchEvent(new Event('focus'));await wait(30);
  assert.deepEqual(lastSnapshot,before);assert.equal(rebuilds.length,count);
 }
 if(config.case==='refusal_notice_and_selection'){
  refuse=true;gate.resolve();await assert.rejects(save,/no longer exists/);await wait(30);
  assert.deepEqual(alerts,['Moving the wall was not saved: That opening no longer exists. Reload the house and choose another.']);
  assert.equal(rebuilds.length,1);assert.deepEqual(rebuilds[0],plan);
  assert.deepEqual(window.__editor.selected(),selection);
 }
 if(config.case==='dropped_dependencies_share_one_notice'){
  const next={...operation,wall:'dependent'},nextLocal=applyLocal(local,next).plan;
  const dependent=hooks.op(next,{drag:true,local:nextLocal,label:'Moving the other wall',selection:{pieceId:'dependent',buildingId:'b'}});
  const refused=assert.rejects(save,/no longer exists/),dropped=assert.rejects(dependent,/Missing wall/);
  refuse=true;gate.resolve();await Promise.all([refused,dropped]);await wait(30);
  assert.deepEqual(alerts,['Moving the wall was not saved: That opening no longer exists. Reload the house and choose another.\nAlso undone because it needed that change: Moving the other wall.']);
  assert.equal(rebuilds.length,1);assert.deepEqual(rebuilds[0],plan);
  assert.deepEqual(window.__editor.selected(),selection);assert.equal(writes.length,1);
 }
 if(config.case==='undo_waits_for_in_flight_step'){
  assert.equal(document.getElementById('rail-undo').disabled,false);
  document.body.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'z',ctrlKey:true}));
  await wait(20);assert.deepEqual(reverts,[]);gate.resolve();await save;
  await until(()=>reverts.length===1);assert.deepEqual(reverts,[0]);
 }
 if(config.case==='undo_refuses_over_foreign_round_after_replay'){
  gate.resolve();await until(()=>answerReady);
  plan.buildings[0].name='Foreign writer';record();
  window.dispatchEvent(new Event('focus'));await until(()=>lastSnapshot.rounds.at(-1).id===2);
  holdAnswer.resolve();await save;
  document.body.dispatchEvent(new KeyboardEvent('keydown',{bubbles:true,cancelable:true,key:'z',ctrlKey:true}));
  await until(()=>alerts.includes(CHANGED_SINCE));assert.deepEqual(reverts,[]);
 }
 if(config.case==='second_release_is_local_while_first_saves'){
  const secondLocal=applyLocal(local,operation).plan;
  const second=hooks.op(operation,{drag:true,local:secondLocal});
  assert.deepEqual(sceneOptions.getPlan(),secondLocal);
  assert.equal(document.getElementById('editor-save-state').textContent,'Saving 2 changes');
  assert.equal(writes.length,1);assert.equal(rebuilds.length,0);
  gate.resolve();await Promise.all([save,second]);await wait(30);
  assert.equal(writes.length,2);assert.deepEqual(sceneOptions.getPlan(),secondLocal);
  assert.equal(rebuilds.length,0);assert.equal(document.getElementById('editor-save-state').textContent,'Saved');
  await press(document.getElementById('rail-undo'));await until(()=>reverts.length===1);
  assert.deepEqual(reverts,[1]);
 }
 if(config.case==='multi_round_gesture_keeps_its_history_turn'){
  const inGroup=deferred(),continueGroup=deferred();
  const group=drawOptions.gesture(async()=>{
   await drawOptions.op({op:'resize_opening',building:'b',id:'door',width:4});
   inGroup.resolve();await continueGroup.promise;
   await drawOptions.op({op:'resize_opening',building:'b',id:'door',width:5});
  });
  const later=hooks.op(operation,{drag:true,local:applyLocal(local,operation).plan});
  gate.resolve();await save;await until(()=>writes.length===2);await inGroup.promise;continueGroup.resolve();
  let finished=false;Promise.all([group,later]).then(()=>finished=true);
  await until(()=>finished);
  assert.deepEqual(writes.map(w=>w.op.op),['move_wall','resize_opening','resize_opening','move_wall']);
 }
 if(config.case.startsWith('signed_out_')){
  const later=hooks.op(operation,{drag:true,local:applyLocal(local,operation).plan});
  signOutStatus=Number(config.case.slice(-3));gate.resolve();
  await until(()=>alerts.length===1);
  assert.match(alerts[0],/^Home Assistant signed this tab out\./);
  assert.equal(document.getElementById('editor-save-state').textContent,'2 changes not saved');
  await wait(25);assert.equal(writes.length,1);
  signOutStatus=null;window.dispatchEvent(new Event('focus'));
  await Promise.all([save,later]);assert.equal(alerts.length,1);
  assert.equal(document.getElementById('editor-save-state').textContent,'Saved');
 }
 if(config.case==='raw_sender_does_not_alert'){
  gate.resolve();await save;
  const {sendOp}=await import(file('static/twin/editor/api.js'));
  await assert.rejects(sendOp({op:'refuse'}),error=>error.status===400&&/no longer exists/.test(error.message));
  assert.deepEqual(alerts,[]);
 }
 if(config.case==='start_over_clears_the_queue_base'){
  gate.resolve();await save;await wait(30);
  await press(document.getElementById('menu-start-over'));
  await until(()=>lastSnapshot.rounds.length===0);
  assert.equal(sceneOptions.getPlan(),null);assert.deepEqual(editorView.plan.buildings,[]);
  assert.deepEqual(alerts,[]);
 }
 if(config.case==='leaving_with_unsaved_warns'){
  const pending=new Event('beforeunload',{cancelable:true});window.dispatchEvent(pending);
  assert.ok(pending.defaultPrevented||pending.returnValue==='');
  gate.resolve();await save;const clean=new Event('beforeunload',{cancelable:true});window.dispatchEvent(clean);
  assert.equal(clean.defaultPrevented,false);
 }
 ok(config.case);ok('no_browser_dialogs');
 assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
 window.dispatchEvent(new Event('pagehide'));console.log(`${passed}/${passed} queue editor checks passed`);process.exit(0);
}catch(error){console.error(error);process.exit(1);}
"""

if __name__ == '__main__':
    ids = sorted(set(re.findall(r'id="([\w-]+)"', (ROOT / 'templates/house_editor.html').read_text(encoding='utf-8'))) | {'piece-card', 'rail-undo', 'rail-redo', 'rail-add-effect', 'editor-save-state'})
    failed = 0
    for case in ('outline_object_settles', 'server_correction_remaps_selection', 'kept_release_draws_once', 'stale_poll_ignored', 'refusal_notice_and_selection', 'dropped_dependencies_share_one_notice',
                 'undo_waits_for_in_flight_step', 'undo_refuses_over_foreign_round_after_replay',
                 'second_release_is_local_while_first_saves', 'multi_round_gesture_keeps_its_history_turn',
                 'signed_out_401', 'signed_out_403', 'raw_sender_does_not_alert', 'start_over_clears_the_queue_base', 'leaving_with_unsaved_warns'):
        failed += bool(run(DRIVER, {'stubs': STUBS, 'ids': ids, 'case': case}, timeout=45))
    sys.exit(bool(failed))
