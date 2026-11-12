"""Solar add/resize/source/undo/redo through real history and local app routes.

Runs the browser fixture's server half only. No Chromium or timing changes.
"""
import copy
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent))
from twin_live_node_rig import run

DRIVER = r"""
try {
 const nativeFetch=globalThis.fetch,errors=[],alerts=[];
 window.chfBase=config.url;window.showGlobalAlert=message=>alerts.push(message);
 let releaseRedo=null,holdRedo=false;
 globalThis.fetch=async(url,init={})=>{
  if(holdRedo && String(url).endsWith('twin/revert')){holdRedo=false;await new Promise(resolve=>{releaseRedo=resolve;});}
  return nativeFetch(url,{...init,headers:{...init.headers,'X-Member-Token':config.token}});
 };
 for(const id of ['rail-undo','rail-redo']){const n=document.createElement('button');n.id=id;document.body.append(n);}
 const {createHistory}=await import(file('static/twin/editor/history.js'));
 const api=await import(file('static/twin/editor/api.js'));
 const read=()=>api.request('state');let state=await read(),releaseResize;
 const current=()=>state.rounds.filter(r=>!r.stale).at(-1).id;
 const refresh=async()=>{state=await read();};
 const history=createHistory({getRound:current,getBuild:()=>null,canEdit:()=>true,refresh,latest:refresh,
  signal:new AbortController().signal,onError:e=>errors.push(e.message)});
 const apply=(op,pause=false)=>history.perform(async()=>{
  const result=await api.op(op);
  if(pause)await new Promise(resolve=>{releaseResize=resolve;});
  await refresh();return result;
 });
 const until=async predicate=>{for(let i=0;i<500&&!predicate();i++)await wait(10);assert.ok(predicate(),'history settles');};
 const idle=()=>!document.getElementById('rail-undo').disabled;
 const zone=s=>s.model.buildings.find(b=>b.id===config.create.building).solar_zones[0];
 const created=await apply(config.create),rect=[...zone(state).rect];rect[2]+=4;
 const resize=apply({op:'update_solar_zone',building:config.create.building,id:zone(state).id,rect},true);
 await until(()=>!!releaseResize);
 const source=apply({op:'set_solar_source',building:config.create.building,roof:config.create.roof});
 releaseResize();const [resized,sourced]=await Promise.all([resize,source]);
 assert.notEqual(created.round,resized.round);assert.notEqual(resized.round,sourced.round);
 assert.equal(state.model.solar_source_roof,config.create.roof);assert.deepEqual(zone(state).rect,rect);
 console.log('  ok actual add, resize and queued source requests create distinct stored rounds');
 await press(document.getElementById('rail-undo'));await until(idle);await refresh();
 assert.equal(state.model.solar_source_roof,null);assert.deepEqual(zone(state).rect,rect);
 console.log('  ok real history undo removes only the source designation and retains the resize');
 holdRedo=true;await press(document.getElementById('rail-redo'));await until(()=>!!releaseRedo);
 await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 const pending=await read();assert.equal(pending.model.solar_source_roof,null);assert.equal(idle(),false);
 console.log('  ok two animation frames do not complete a pending redo request');
 releaseRedo();await until(idle);await refresh();
 assert.equal(state.model.solar_source_roof,config.create.roof);assert.deepEqual(zone(state).rect,rect);
 assert.deepEqual(errors,[]);assert.deepEqual(alerts,[]);assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
 console.log('  ok completed redo restores the actual stored source round without losing the resized zone');
 console.log('4/4 real-route history checks passed');process.exit(0);
}catch(error){console.error(error);process.exit(1);}
"""


def main():
    import test_house_twin_energy_live as fixture
    served = fixture.setup()
    assert served is not None, 'The server-side fixture must start'
    try:
        from services import twin_store
        model = twin_store.current_model()
        building = next(b for b in model['buildings'] if b.get('solar_zones'))
        zone = building['solar_zones'][0]
        u = round(((zone['rect'][0]+zone['rect'][2])/2-2)*12)/12
        v = round((zone['rect'][1]+zone['rect'][3])*6)/12
        def clear(model):
            model = copy.deepcopy(model)
            for b in model['buildings']:
                b['solar_zones'] = []
            model['solar_source_roof'] = None
            return model
        twin_store.update_model(clear, note='History regression starts without a solar zone')
        create = dict(op='add_solar_zone', building=building['id'], roof=zone['roof'],
                      plane=zone['plane'], rect=[u-2,v-3,u+2,v+3])
        return run(DRIVER, {'url': served.url(), 'token': fixture.L.H.STATE['token'], 'create': create}, timeout=90)
    finally:
        served.stop()


if __name__ == '__main__':
    sys.exit(main())
