"""Run the real thermostat Serves control and its model commits under Node."""
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const {createHaLink}=await import(file('static/twin/editor/ha_link.js'));
const room=(id,name,level='L1',extra={})=>({id,name,level,ha_area:'a',polygon:[[0,0],[10,0],[10,10],[0,10]],...extra});
function setup({saved,available=true}={}) {
 const plan={buildings:[{id:'b',levels:[{id:'L1',name:'Main floor'},{id:'L2',name:'Upstairs'}],rooms:[room('hall','Hall'),room('office','Office'),room('bed','Bedroom','L2'),room('ghost','Ghost','L1',{state:'ghost'})],
  devices:[{device:'thermo',host:{floor:'hall',u:.5,v:.5}}]}],site:{yard_rooms:[{id:'yard',name:'Garden'}]}};
 if(saved)plan.climate_zones={'climate.hall':saved};
 const body={available,areas:[{area_id:'a',name:'Hall'}],rooms:[{building:'b',room:'hall',ha_area:'a'}],devices:available?[
  {device_id:'thermo',entity_id:'climate.hall',name:'Thermostat',kind:'climate',area_id:'a'},
  {device_id:'lamp',entity_id:'light.hall',name:'Lamp',kind:'light',area_id:'a'}]:[]};
 const sent=[],errors=[],abort=new AbortController();let editable=true;
 const api={request:async()=>body,report:e=>errors.push(e)};
 const link=createHaLink({api,signal:abort.signal,getPlan:()=>plan,canEdit:()=>editable,onCommit:async op=>{sent.push(structuredClone(op));}});
 const host=document.createElement('div');document.body.append(host);
 const record={kind:'room',piece:plan.buildings[0].rooms[0],building:plan.buildings[0]};
 return {plan,body,sent,errors,abort,link,host,record,lock:()=>editable=false,draw:()=>link.draw(host,record),stop(){abort.abort();host.remove();}};
}
const settle=()=>new Promise(r=>setTimeout(r,5));
const serves=s=>s.host.querySelector('[aria-label="Serves"]');
const checkbox=(s,name)=>s.host.querySelectorAll('input').find(n=>n.getAttribute('aria-label')===name);
await test('thermostat only has Serves with computed default and one op per scope or checklist change',async()=>{
 const s=setup();try{await s.link.refresh();s.draw();
  assert.equal(s.host.querySelectorAll('[aria-label="Serves"]').length,1);assert.match(textOf(s.host),/Whole house \(default\)/);
  assert.match(textOf(s.host),/Except/);assert.ok(checkbox(s,'Office · Main floor'));assert.equal(checkbox(s,'Ghost · Main floor'),undefined);
  serves(s).value='rooms';fire(serves(s),'change');await settle();assert.equal(s.sent.length,1);
  assert.deepEqual(s.sent[0],{op:'set_climate_zone',entity:'climate.hall',scope:'rooms',rooms:[],except:[]});
  const own=checkbox(s,'Hall · Main floor');assert.equal(own.checked,true);assert.equal(own.disabled,true);
  const office=checkbox(s,'Office · Main floor');office.checked=true;fire(office,'change');await settle();assert.equal(s.sent.length,2);assert.deepEqual(s.sent[1].rooms,['office']);
  const yard=checkbox(s,'Garden · Yard');yard.checked=true;fire(yard,'change');await settle();assert.equal(s.sent.length,3);assert.deepEqual(s.sent[2].rooms,['office','yard']);
  assert.deepEqual(s.errors,[]);
 }finally{s.stop();}
});
await test('multiple placed thermostats compute floor default and placement changes invalidate the control',async()=>{
 const s=setup();try{await s.link.refresh();s.draw();assert.equal(serves(s).value,'house');
  s.body.devices.push({device_id:'second',entity_id:'climate.bed',kind:'climate',area_id:'other'});
  s.plan.buildings[0].devices.push({device:'second',host:{floor:'bed',u:.5,v:.5}});
  assert.equal(s.draw(),true);assert.equal(serves(s).value,'floor');assert.match(textOf(s.host),/Whole floor \(default\)/);assert.equal(s.sent.length,0);
 }finally{s.stop();}
});
await test('saved setting values read-only and clear to computed default',async()=>{
 const s=setup({saved:{scope:'floor',rooms:[],except:['office']}});try{await s.link.refresh();s.draw();assert.equal(checkbox(s,'Office · Main floor').checked,true);
  await click(s.host.querySelectorAll('button').find(n=>textOf(n)==='Use default'));await settle();assert.deepEqual(s.sent,[{op:'set_climate_zone',entity:'climate.hall',scope:null}]);
  s.lock();s.draw();assert.equal(serves(s).disabled,true);assert.ok(s.host.querySelectorAll('input').every(n=>n.disabled));
  const before=s.sent.length;serves(s).value='house';fire(serves(s),'change');await settle();assert.equal(s.sent.length,before);assert.deepEqual(s.errors,[]);
 }finally{s.stop();}
});
await test('Serves focus survives redraw without replacing the area selector',async()=>{
 const s=setup();try{await s.link.refresh();s.draw();serves(s).focus();
  s.plan.climate_zones={'climate.hall':{scope:'rooms',rooms:['office'],except:[]}};
  assert.equal(s.draw(),true);assert.equal(document.activeElement,serves(s));assert.equal(serves(s).value,'rooms');
  assert.ok(s.host.querySelector('[aria-label="Home Assistant area"]'));assert.equal(checkbox(s,'Hall · Main floor').disabled,true);
  const office=checkbox(s,'Office · Main floor');office.focus();s.plan.climate_zones['climate.hall'].rooms=[];s.draw();
  assert.equal(document.activeElement,checkbox(s,'Office · Main floor'));
 }finally{s.stop();}
});
await test('no HA still edits stored zone with one op',async()=>{
 const s=setup({available:false,saved:{scope:'house',rooms:[],except:['office']}});try{await s.link.refresh();s.draw();assert.equal(serves(s).value,'house');
  const office=checkbox(s,'Office · Main floor');office.checked=false;fire(office,'change');await settle();assert.equal(s.sent.length,1);assert.deepEqual(s.sent[0].except,[]);assert.deepEqual(s.errors,[]);
 }finally{s.stop();}
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output, end='')
    sys.exit(code or 0)
