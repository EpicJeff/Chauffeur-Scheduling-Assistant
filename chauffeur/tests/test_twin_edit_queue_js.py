"""The editor queue runs real local operations with scripted I/O. Run from chauffeur/."""
from pathlib import Path

from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]

DRIVER = r"""
const {createEditQueue} = await import(file('static/twin/editor/edit_queue.js'));
const {applyLocal, LocalMissing} = await import(file('static/twin/editor/local_ops.js'));
const house = () => ({buildings:[{id:'house',levels:[{id:'L1'}],rooms:[],
  joints:[{id:'a',level:'L1',at:[0,0]},{id:'b',level:'L1',at:[0,5]},
    {id:'c',level:'L1',at:[10,0]},{id:'d',level:'L1',at:[10,5]}],
  walls:[{id:'W',level:'L1',joints:['a','b'],from:[0,0],to:[0,5]},
    {id:'V',level:'L1',joints:['c','d'],from:[10,0],to:[10,5]}]}],
  site:{planting:[{id:'tree',at:[20,20]}]}});
const move = (wall='W', by=[1,0]) => ({op:'move_wall',building:'house',wall,by});
const yard = {op:'move_site_item',list:'planting',id:'tree',by:[2,3]};
const apply = (p, op) => applyLocal(p,op)?.plan || p;
const answer = (round,plan) => ({round,plan,model:{round},words:'Saved'});
const error = (status, message='Cannot do that') => Object.assign(new Error(message),{status});
const deferred = () => {let resolve,reject; const promise=new Promise((a,b)=>{resolve=a;reject=b;});
  return {promise,resolve,reject};};
const flush = async () => {for(let i=0;i<20;i++) await Promise.resolve();};
function setup(extra={}) {
  const calls=[], changes=[], delays=[]; let active=0, maxActive=0, signedOut=0;
  const queue=createEditQueue({send:op=>{
    active++; maxActive=Math.max(maxActive,active);
    const d=deferred(); calls.push({op,...d});
    return d.promise.finally(()=>{active--;});
  },onChange:change=>changes.push(change),onSignedOut:()=>{signedOut++;},
  sleep:async ms=>{delays.push(ms);},now:()=>123,...extra});
  const initial=house(); queue.base(answer(1,initial));
  const push=(op,label,local=null)=>queue.push({op,label,selection:{kind:'wall',id:op.wall},local});
  const notices=()=>changes.filter(c=>c.refused?.length || c.dropped?.length);
  return {queue,calls,changes,delays,initial,push,notices,
    get maxActive(){return maxActive;},get signedOut(){return signedOut;}};
}

await test('sends_in_order_one_at_a_time',async()=>{
  const h=setup(), ops=[move(),move('V'),yard];
  assert.deepEqual(h.queue.state(),{saved:true,saving:0,unsaved:0});
  const steps=ops.map((op,i)=>h.push(op,'Step '+i));
  assert.equal(new Set(steps.map(s=>s.id)).size,3);
  assert.equal(h.queue.pending(),3);
  assert.deepEqual(h.queue.state(),{saved:false,saving:3,unsaved:0});
  await flush(); assert.equal(h.calls.length,1);
  let plan=h.initial;
  for(let i=0;i<3;i++) {
    assert.equal(h.calls.length,i+1); assert.equal(h.calls[i].op,ops[i]);
    plan=apply(plan,ops[i]); const result=answer(i+2,plan);
    h.calls[i].resolve(result); assert.equal(await steps[i].saved,result); await flush();
  }
  assert.equal(h.maxActive,1); assert.equal(h.queue.pending(),0);
  assert.equal(h.queue.shown(),plan);
  assert.deepEqual(h.queue.state(),{saved:true,saving:0,unsaved:0});
});

await test('second_step_builds_on_first',async()=>{
  const h=setup(), op=move(), first=apply(h.initial,op), second=apply(first,op);
  const a=h.push(op,'First',first), b=h.push(op,'Second');
  assert.deepEqual(h.queue.shown(),second);
  assert.deepEqual(h.queue.shown().buildings[0].walls[0].from,[2,0]);
  h.calls[0].resolve(answer(2,first)); await a.saved; await flush();
  assert.deepEqual(h.queue.shown(),second);
  h.calls[1].resolve(answer(3,second)); await b.saved;
  assert.equal(h.queue.shown(),second);
});

await test('refusal_snaps_back_only_that_step',async()=>{
  const h=setup(), aOp=move('V'), bOp=move(), aPlan=apply(h.initial,aOp);
  const a=h.push(aOp,'A',aPlan), b=h.push(bOp,'B',apply(aPlan,bOp));
  const c=h.push(yard,'C',apply(h.queue.shown(),yard));
  h.calls[0].resolve(answer(2,aPlan)); await a.saved; await flush();
  const refusal=error(422,'Wall would overlap');
  const rejected=assert.rejects(b.saved,e=>e===refusal && e.refused===true);
  h.calls[1].reject(refusal); await rejected; await flush();
  const final=apply(aPlan,yard);
  assert.deepEqual(h.queue.shown(),final); assert.equal(h.notices().length,0);
  assert.equal(h.calls[2].op,yard);
  h.calls[2].resolve(answer(3,final)); await c.saved; await flush();
  assert.equal(h.notices().length,1);
  assert.deepEqual(h.notices()[0].refused,[{label:'B',reason:'Wall would overlap'}]);
  assert.deepEqual(h.notices()[0].dropped,[]);
});

await test('dependent_step_is_dropped_and_named',async()=>{
  const h=setup(), withWall=house();
  withWall.buildings[0].walls.push({...withWall.buildings[0].walls[0],id:'new-wall'});
  const b=h.push({op:'add_wall'},'B',withWall), c=h.push(move('new-wall'),'C');
  assert.deepEqual(h.queue.shown(),apply(withWall,move('new-wall')));
  const bRejected=assert.rejects(b.saved,e=>e.refused===true);
  const cRejected=assert.rejects(c.saved,e=>e instanceof LocalMissing && e.dropped===true);
  h.calls[0].reject(error(400,'Bad wall')); await Promise.all([bRejected,cRejected]); await flush();
  assert.equal(h.calls.length,1); assert.equal(h.queue.pending(),0);
  assert.equal(h.queue.shown(),h.initial);
  assert.equal(h.notices().length,1); assert.deepEqual(h.notices()[0].dropped,['C']);
  assert.deepEqual(h.notices()[0].refused,[{label:'B',reason:'Bad wall'}]);
});

await test('later_refusal_joins_notice',async()=>{
  const h=setup(), b=h.push(move(),'B'), dOp={op:'add_opening',wall:'W'}, d=h.push(dOp,'D');
  const bRejected=assert.rejects(b.saved,e=>e.refused===true);
  const dRejected=assert.rejects(d.saved,e=>e.refused===true);
  h.calls[0].reject(error(409,'Wall conflict')); await bRejected; await flush();
  assert.equal(h.notices().length,0); assert.equal(h.calls[1].op,dOp);
  h.calls[1].reject(error(422,'Opening conflict')); await dRejected; await flush();
  assert.equal(h.notices().length,1);
  assert.deepEqual(h.notices()[0].refused,[{label:'B',reason:'Wall conflict'},{label:'D',reason:'Opening conflict'}]);
  assert.deepEqual(h.notices()[0].dropped,[]);
  const next=h.push(yard,'Next'); h.calls[2].resolve(answer(2,apply(h.initial,yard)));
  await next.saved; await flush(); assert.equal(h.notices().length,1);
});

await test('network_failure_keeps_edits_and_retries',async()=>{
  const gate=deferred(), delays=[];
  const h=setup({sleep:ms=>{delays.push(ms); return gate.promise;}});
  const op=move(), preview=apply(h.initial,op), a=h.push(op,'A',preview);
  h.calls[0].reject(new Error('offline')); await flush();
  assert.equal(h.queue.shown(),preview); assert.equal(h.queue.pending(),1);
  assert.deepEqual(h.queue.state(),{saved:false,saving:0,unsaved:1});
  assert.deepEqual(delays,[1000]); assert.equal(h.calls.length,1);
  gate.resolve(); await flush(); assert.equal(h.calls.length,2);
  h.calls[1].resolve(answer(2,preview)); await a.saved;
  assert.deepEqual(h.queue.state(),{saved:true,saving:0,unsaved:0});
});

await test('signed_out_stops_sending',async()=>{
  for(const status of [401,403]) {
    const h=setup(), a=h.push(move(),'A'), b=h.push(yard,'B');
    const preview=h.queue.shown();
    h.calls[0].reject(error(status)); await flush();
    assert.equal(h.signedOut,1); assert.equal(h.calls.length,1); assert.deepEqual(h.delays,[]);
    assert.equal(h.queue.shown(),preview);
    assert.deepEqual(h.queue.state(),{saved:false,saving:0,unsaved:2});
    const c=h.push(move('V'),'C'); await flush(); assert.equal(h.calls.length,1);
    h.queue.resume(); h.queue.resume(); await flush(); assert.equal(h.calls.length,2);
    let p=apply(h.initial,move()); h.calls[1].resolve(answer(2,p)); await a.saved; await flush();
    p=apply(p,yard); h.calls[2].resolve(answer(3,p)); await b.saved; await flush();
    p=apply(p,move('V')); h.calls[3].resolve(answer(4,p)); await c.saved;
    assert.equal(h.signedOut,1); assert.equal(h.maxActive,1); assert.deepEqual(h.delays,[]);
  }
});

await test('foreign_round_replays_pending',async()=>{
  const h=setup(), op=move(), local=apply(h.initial,op), a=h.push(op,'A',local);
  const foreignPlan=apply(h.initial,yard);
  assert.equal(h.queue.base(answer(10,foreignPlan)),true);
  const replay=h.queue.shown(); assert.deepEqual(replay,apply(foreignPlan,op));
  assert.notEqual(replay,local);
  const changeCount=h.changes.length;
  assert.equal(h.queue.base(answer(9,house())),false);
  assert.equal(h.queue.shown(),replay); assert.equal(h.changes.length,changeCount);
  // The pending step still settles, but its older answer cannot undo the foreign house.
  const result=answer(2,local); h.calls[0].resolve(result); assert.equal(await a.saved,result);
  assert.equal(h.queue.shown(),foreignPlan); assert.equal(h.queue.pending(),0);
});

await test('answer_replays_later_local_and_keeps_shown_identity',async()=>{
  const h=setup(), op=move(), first=apply(h.initial,op), second=apply(first,op);
  const a=h.push(op,'A',first), b=h.push(op,'B',second);
  assert.equal(h.queue.shown(),second); assert.equal(h.queue.shown(),second);
  const server=apply(first,yard);
  h.calls[0].resolve(answer(2,server)); await a.saved; await flush();
  const replay=h.queue.shown(); assert.deepEqual(replay,apply(server,op));
  assert.notEqual(replay,second); assert.equal(h.queue.shown(),replay);
  h.calls[1].resolve(answer(3,replay)); await b.saved;
});

await test('retry_backoff_caps_resets_and_counts_all_pending',async()=>{
  const h=setup(), a=h.push(move(),'A'), b=h.push(yard,'B');
  for(let i=0;i<6;i++) {h.calls[i].reject(error(503)); await flush();}
  assert.deepEqual(h.delays,[1000,2000,5000,10000,10000,10000]);
  const p=apply(h.initial,move()); h.calls[6].resolve(answer(2,p)); await a.saved; await flush();
  h.calls[7].reject(error(502)); await flush(); assert.equal(h.delays.at(-1),1000);
  h.calls[8].resolve(answer(3,apply(p,yard))); await b.saved;
  assert.equal(h.notices().length,0); assert.equal(h.maxActive,1);
  const gate=deferred(); const waiting=setup({retryMs:[7,11],sleep:ms=>{
    assert.equal(ms,7); return gate.promise;
  }});
  const c=waiting.push(move(),'C'), d=waiting.push(yard,'D');
  waiting.calls[0].reject(error(500)); await flush();
  assert.deepEqual(waiting.queue.state(),{saved:false,saving:0,unsaved:2});
  gate.resolve(); await flush(); waiting.calls[1].resolve(answer(2,p)); await c.saved; await flush();
  waiting.calls[2].resolve(answer(3,apply(p,yard))); await d.saved;
});

await test('foreign_missing_unsent_is_dropped_but_in_flight_stays',async()=>{
  const h=setup(), a=h.push(move(),'A'), b=h.push(move('V'),'B');
  const foreign=house(); foreign.buildings[0].walls=[];
  const rejected=assert.rejects(b.saved,e=>e.dropped===true);
  h.queue.base(answer(10,foreign)); await rejected; await flush();
  assert.equal(h.queue.pending(),1); assert.equal(h.queue.shown(),foreign);
  assert.equal(h.calls.length,1); assert.equal(h.notices().length,0);
  h.calls[0].resolve(answer(11,foreign)); await a.saved; await flush();
  assert.equal(h.notices().length,1); assert.deepEqual(h.notices()[0].dropped,['B']);
});

await test('unawaited_rejections_are_handled',async()=>{
  const h=setup(), withWall=house();
  withWall.buildings[0].walls.push({...withWall.buildings[0].walls[0],id:'new-wall'});
  h.push({op:'add_wall'},'B',withWall); h.push(move('new-wall'),'C');
  h.calls[0].reject(error(400)); await flush();
  // Give node an event-loop turn to detect unhandled saved rejections.
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(h.queue.pending(),0); assert.equal(h.notices().length,1);
});
finish();
"""


def run():
    code, output = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix()})
    print(output, end='')
    if code is not None:
        assert code == 0, output


if __name__ == '__main__':
    run()
