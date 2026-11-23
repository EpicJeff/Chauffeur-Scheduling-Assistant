"""Real mounted mode controls, combinations, storage and offline behavior under Node."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {MODE_STORAGE_KEY}=await import(file('static/twin/live/mode_state.js'));
const ids=['lights','climate','energy','security'];
const checks=[],check=(name,fn)=>checks.push([name,fn]);
const button=id=>document.querySelector(`[data-mode="${id}"]`);
const event=(node,type,init={})=>node.dispatchEvent(new PointerEvent(type,{bubbles:true,cancelable:true,...init}));
const devices=[
 {device_id:'lamp',name:'Lamp',kind:'light',entity_id:'light.a',state:'on',attributes:{brightness:255}},
 {device_id:'thermo',name:'Thermostat',kind:'climate',entity_id:'climate.a',state:'heat',attributes:{current_temperature:68,temperature:72,hvac_action:'heating'}},
 {device_id:'camera',name:'Camera',kind:'camera',entity_id:'camera.a',state:'idle'},
 {device_id:'lock',name:'Door',kind:'lock',entity_id:'lock.a',state:'unlocked'},
 {device_id:'solar',name:'Solar',kind:'power',entity_id:'sensor.solar_power',state:'2000',attributes:{device_class:'power',unit_of_measurement:'W'}},
 {device_id:'panel',name:'Panel',kind:'power',entity_id:'sensor.house_power',state:'2000',attributes:{device_class:'power',unit_of_measurement:'W'}}];
function tagged(t,tag){const out=[];t.view.scene.traverse(o=>{if(o.userData[tag])out.push(o);});return out;}
check('every combination independently controls lights, climate, ribbons, legends and cones',async()=>{
 const t=await rig({devices});try{
  t.live.stop();t.view.tier='medium';const lighting=[];t.view.setLiveLamps=on=>lighting.push(on);
  const b=t.view.plan.buildings[0];b.roof={sections:[{id:'roof',kind:'flat',rect:[-40,-10,40,20],pitch:0,plate:10,overhang:0,level:'L1'}]};
  b.solar_zones=[{id:'z',roof:'roof',plane:[0,0,10],rect:[-30,-5,-10,5]}];
  t.live=await liveModule.mountLive(t.view,{api:t.api});
  assert.deepEqual(t.live.modes(),ids);assert.equal(t.view.live.mode,'all');
  const cone=tagged(t,'cameraCone')[0],red=tagged(t,'securityAttention'),floors=tagged(t,'lightWash');
  assert.ok(cone&&red.length&&floors.length);assert.ok(t.live.energy().ribbons.some(r=>r.visible));
  for(let bits=0;bits<16;bits++){
   const enabled=ids.filter((_,i)=>bits&(1<<i));t.live.setModes(enabled);t.live.draw();
   assert.deepEqual(t.live.modes(),enabled);
   for(const id of ids)assert.equal(button(id).getAttribute('aria-pressed'),String(enabled.includes(id)));
   assert.equal(button('all').getAttribute('aria-pressed'),String(bits===15));
   assert.equal(cone.visible,enabled.includes('security'));
   assert.equal(red.some(o=>o.visible),enabled.includes('security'));
   assert.equal(document.querySelector('.twin-climate-labels').hidden,!enabled.includes('climate'));
   assert.equal(floors.some(f=>f.parent.visible),enabled.includes('climate'));
   assert.equal(t.live.lights().some(l=>l.real),enabled.includes('lights'));
   assert.equal(lighting.at(-1),enabled.includes('lights'));
   assert.equal(t.live.energy().ribbons.some(r=>r.visible),enabled.includes('energy'));
   assert.equal(document.querySelector('.twin-energy-labels').hidden,!enabled.includes('energy'));
   assert.equal(!!document.getElementById('twin-mode-legend').querySelector('a'),enabled.includes('energy'));
   assert.equal(t.live.marker('lamp').dim,false,'enabled markers never dim');
   assert.equal(t.sprite('lamp').visible,enabled.includes('lights'));
   assert.equal(t.live.marker('lock').look,'attention','attention marker remains reachable');
  }
  t.live.setMode('climate');t.states['climate.a'].attributes.hvac_action='idle';await t.live.refresh();
  assert.equal(floors[0].parent.visible,true);assert.equal(floors[0].material.opacity,.35);
  t.live.toggleMode('energy');assert.equal(floors[0].parent.visible,false,'idle grey stays solo-only');
  t.live.setMode('all');assert.deepEqual(t.live.modes(),ids);
  for(const id of ids){t.live.setMode(id);assert.deepEqual(t.live.modes(),[id]);assert.equal(t.live.mode,id);}
  t.live.setMode('unknown');assert.equal(t.live.mode,'all');
  await press(button('all'));assert.deepEqual(t.live.modes(),[]);assert.equal(t.live.mode,'none');
  await press(button('lights'));assert.deepEqual(t.live.modes(),['lights']);
  await press(button('energy'));assert.deepEqual(t.live.modes(),['lights','energy']);assert.equal(t.live.mode,'custom');
  await press(button('all'));assert.deepEqual(t.live.modes(),ids);
 }finally{t.cleanup();}
});
check('hold touch or mouse solos once; release never toggles; cancellation and desktop shortcuts work',async()=>{
 const t=await rig({devices:[]});try{
  for(const pointerType of ['touch','mouse']){
   t.live.setMode('all');event(button('energy'),'pointerdown',{pointerType});await wait(550);
   assert.deepEqual(t.live.modes(),['energy']);event(button('energy'),'pointerup',{pointerType});event(button('energy'),'click');
   assert.deepEqual(t.live.modes(),['energy']);
   event(button('energy'),'pointerdown',{pointerType});event(button('energy'),'pointerup',{pointerType});event(button('energy'),'click');
   assert.deepEqual(t.live.modes(),[],'the next ordinary tap still works');
  }
  for(const cancel of ['pointercancel','pointerleave','blur']){
   t.live.setMode('all');event(button('lights'),'pointerdown');event(button('lights'),cancel);await wait(550);assert.equal(t.live.mode,'all');
  }
  event(button('security'),'contextmenu',{button:2});assert.deepEqual(t.live.modes(),['security']);
  event(button('security'),'click');assert.deepEqual(t.live.modes(),['security'],'native touch context menu cannot also tap');
  button('climate').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey:true,cancelable:true}));assert.deepEqual(t.live.modes(),['climate']);
  button('lights').dispatchEvent(new MouseEvent('click',{shiftKey:true,bubbles:true}));assert.deepEqual(t.live.modes(),['lights']);
  for(const id of ids){assert.match(button(id).title,/Hold.*right-click.*Shift\+click.*Shift\+Enter/);assert.match(button(id).getAttribute('aria-description'),/show only/);}
  event(button('energy'),'pointerdown');t.cleanup();await wait(550);assert.equal(document.getElementById('twin-modes'),null);
 }finally{t.cleanup();}
});
check('device storage round trips custom and empty selections, invalid and throwing storage fall back safely',async()=>{
 const original=window.localStorage, data=new Map();
 window.localStorage={getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};
 try{
  let t=await rig({devices:[]});assert.deepEqual(t.live.modes(),ids);t.live.setModes(['lights','security']);t.cleanup();
  t=await rig({devices:[]});assert.deepEqual(t.live.modes(),['lights','security']);assert.equal(t.live.mode,'custom');t.live.setModes([]);t.cleanup();
  t=await rig({devices:[]});assert.deepEqual(t.live.modes(),[]);t.cleanup();
  for(const value of ['bad json','{}','["removed"]']){
   data.set(MODE_STORAGE_KEY,value);t=await rig({devices:[]});assert.deepEqual(t.live.modes(),ids);t.cleanup();
  }
  Object.defineProperty(window,'localStorage',{configurable:true,get(){throw Error('blocked');}});
  t=await rig({devices:[]});assert.deepEqual(t.live.modes(),ids);t.live.toggleMode('lights');assert.equal(t.live.mode,'custom');t.cleanup();
  Object.defineProperty(window,'localStorage',{configurable:true,writable:true,value:{getItem:()=>null,setItem(){throw Error('quota');}}});
  t=await rig({devices:[]});t.live.setMode('security');assert.deepEqual(t.live.modes(),['security']);t.cleanup();
 }finally{Object.defineProperty(window,'localStorage',{configurable:true,writable:true,value:original});}
});
check('offline fire-only live layer shares the same controls, storage and mode readers',async()=>{
 const t=await rig({devices:[]});try{
  t.live.stop();t.view.plan.effect_fixtures=[{id:'fire',type:'fire',at:[0,0,0],always_on:true}];
  t.live=await liveModule.mountLive(t.view,{layout:{available:false}});assert.ok(t.live?.offlineEffects);
  await press(button('all'));assert.equal(t.live.mode,'none');
  t.live.setModes(['climate','security']);assert.deepEqual(t.live.modes(),['climate','security']);
  t.live.setMode('lights');assert.equal(t.live.mode,'lights');
 }finally{t.cleanup();}
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} mode checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
