"""Mounted legend keys and mode providers, executed in the live-layer Node rig."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const checks=[],check=(name,fn)=>checks.push([name,fn]);
const keyModule=await import(file('static/twin/live/mode_key.js'));
const {mountModeKey,LEGEND_STORAGE_KEY}=keyModule;
const {climateColors,registerClimate}=await import(file('static/twin/live/climate.js'));
const {FLOW_COLORS,energyKey}=await import(file('static/twin/live/energy.js'));
const {alarmSummary,mountSecurity,SECURITY_COLOR}=await import(file('static/twin/live/security.js'));
const sections=()=>[...document.querySelectorAll('[data-mode-key]')].map(n=>n.dataset.modeKey);
const click=node=>node.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
check('test_sections_only_for_active_modes',async()=>{
 const t=await rig({devices:[]});try{
  const button=document.getElementById('twin-mode-key-button'),card=document.getElementById('twin-mode-key');
  assert.ok(button);assert.equal(button.getAttribute('aria-label'),'Legend');assert.equal(card.hidden,true);
  assert.equal(card.getAttribute('role'),'dialog');assert.equal(card.getAttribute('aria-label'),'Legend');
  t.live.setModes(['security','climate']);click(button);assert.deepEqual(sections(),['climate','security']);
  t.live.toggleMode('climate');assert.deepEqual(sections(),['security']);assert.equal(card.hidden,false);
  t.live.setModes([]);assert.equal(button.hidden,true);assert.equal(card.hidden,true);assert.deepEqual(sections(),[]);
  t.live.setMode('climate');assert.equal(card.hidden,true);
 }finally{t.cleanup();}assert.equal(document.getElementById('twin-mode-key'),null);
});
check('test_swatches_use_mode_constants',async()=>{
 let climate;registerClimate(mode=>climate=mode);
 assert.deepEqual(climate.key().items.map(i=>i.swatch),Object.values(climateColors).map(rgb=>`rgb(${rgb.join(', ')})`));
 assert.deepEqual(climate.key().items.map(i=>i.label),['Heating','Cooling','Idle']);
 const energy=energyKey('');assert.deepEqual(energy.items.map(i=>i.swatch),['solar','battery','grid','car'].map(k=>FLOW_COLORS[k]));
 assert.deepEqual(energy.items.map(i=>i.label),['Solar','Battery','Grid','Car charger']);
 assert.equal(energy.note,'Flows under 50 W are hidden');
 const t=await rig({devices:[]});try{t.live.setMode('security');const rows=document.querySelectorAll('[data-mode-key="security"] .twin-key-row');
 assert.equal(rows[0].firstChild.style.backgroundColor,SECURITY_COLOR);assert.equal(rows[1].textContent.replace('◁',''),'Camera view · 25 ft');
 assert.ok(rows[1].querySelector('[data-key-cone]'));
 }finally{t.cleanup();}
});
check('test_alarm_summary',async()=>{
 assert.equal(alarmSummary([{state:'armed_away'},{state:'armed_away'}],false),'Alarm · armed away (2 of 2)');
 assert.equal(alarmSummary([{state:'disarmed'},{state:'armed_home'},{state:'armed_home'}],false),'Alarm · armed home (2 of 3)');
 assert.equal(alarmSummary([{state:'armed_away'}],true),'Alarm · unavailable');
 assert.equal(alarmSummary([{state:'unavailable'},{state:'unknown'},{}],false),'Alarm · unavailable');
 assert.equal(alarmSummary([],false),'');assert.equal(alarmSummary([],true),'');
 const t=await rig({devices:[{device_id:'a',kind:'alarm',entity_id:'alarm_control_panel.a',name:'Front',state:'armed_home',attributes:{friendly_name:'Front'}},
  {device_id:'b',kind:'alarm',entity_id:'alarm_control_panel.b',name:'Back',state:'disarmed',attributes:{friendly_name:'Back'}}]});
 try{t.live.setMode('security');const card=document.getElementById('twin-mode-key'),details=card.querySelector('details');
  assert.ok(details);assert.equal(!!details.open,false);assert.match(details.querySelector('summary').textContent,/Alarm · armed home \(1 of 2\)/);
  assert.match(details.textContent,/Front: armed home/);assert.match(details.textContent,/Back: disarmed/);
  t.states['alarm_control_panel.b'].state='armed_home';await t.live.refresh();assert.equal(card.querySelector('details'),null);
  assert.match(card.textContent,/Alarm · armed home \(2 of 2\)/);
  const layer=mountSecurity({view:t.view,live:{...t.live,stale:()=>true}});
  try{assert.equal(layer.key().status,'Alarm · unavailable');assert.deepEqual(layer.key().content,[]);}finally{layer.stop();}
 }finally{t.cleanup();}
});
check('test_no_button_without_keys',()=>{
 const strip=document.createElement('fieldset');document.body.append(strip);let data=[];
 const key=mountModeKey(strip,{getSections:()=>data,storage:null});
 assert.equal(key.button.hidden,true);assert.equal(key.card.hidden,true);
 data=[{id:'empty',name:'Empty',key:{items:[]}}];key.update();assert.equal(key.button.hidden,true);
 data=[{id:'lights',name:'Lights',key:{items:[],note:'Some lights are shown as glow only on this tier'}}];key.update();
 assert.equal(key.button.hidden,false);click(key.button);assert.equal(key.card.hidden,false);key.stop();strip.remove();
});
check('test_open_state_persists',()=>{
 const data=new Map(),storage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)};
 const strip=document.createElement('fieldset');document.body.append(strip);
 const options={getSections:()=>[{id:'a',name:'A',key:{items:[{swatch:'red',label:'On'}]}}],storage};
 let key=mountModeKey(strip,options);assert.equal(key.card.hidden,true);click(key.button);assert.equal(data.get(LEGEND_STORAGE_KEY),'true');
 key.stop();key=mountModeKey(strip,options);assert.equal(key.card.hidden,false);assert.equal(key.button.getAttribute('aria-expanded'),'true');
 key.card.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
 assert.equal(key.card.hidden,true);assert.equal(document.activeElement,key.button);assert.equal(data.get(LEGEND_STORAGE_KEY),'false');
 click(key.button);click(strip);assert.equal(key.card.hidden,false,'strip controls do not dismiss');
 click(document.body);assert.equal(key.card.hidden,true,'scene/outside tap dismisses');
 key.stop();key=mountModeKey(strip,{...options,storage:{getItem(){throw Error('blocked');},setItem(){throw Error('quota');}}});
 click(key.button);assert.equal(key.card.hidden,false);key.close();key.stop();strip.remove();
});
check('test_card_position_clears_glance_and_reflows',()=>{
 const strip=document.createElement('fieldset'),glance=document.createElement('div');glance.id='twin-glance-home';document.body.append(strip,glance);
 const original=[window.innerWidth,window.innerHeight];
 const key=mountModeKey(strip,{getSections:()=>[{id:'a',name:'A',key:{items:[{swatch:'red',label:'On'}]}}],storage:null});
 try{for(const [width,height,top,glanceTop]of [[1920,1080,16,970],[390,844,206,740]]){
  window.innerWidth=width;window.innerHeight=height;strip._rect={left:width/2-159,right:width/2+159,top,bottom:top+54,width:318,height:54};
  glance._rect={left:16,right:width-16,top:glanceTop,bottom:height-16,width:width-32,height:height-16-glanceTop};
  key.card._rect={width:220};if(key.card.hidden)click(key.button);window.dispatchEvent(new Event('resize'));
  assert.equal(key.card.style.top,`${top+62}px`);assert.equal(key.card.style.left,`${width/2-110}px`);
  assert.equal(key.card.style.getPropertyValue('--twin-key-space'),`${glanceTop-top-74}px`);
 }}finally{[window.innerWidth,window.innerHeight]=original;key.stop();strip.remove();glance.remove();}
});
check('test_energy_content_inside_energy_section',async()=>{
 const t=await rig({devices:[]});try{
  t.live.setModes(['climate','energy','security']);const card=document.getElementById('twin-mode-key');click(document.getElementById('twin-mode-key-button'));
  const link=card.querySelector('a');assert.equal(link.textContent,'Why no ribbons?');assert.equal(link.closest('[data-mode-key]').dataset.modeKey,'energy');
  click(link);const panel=card.querySelector('.twin-energy-check');assert.equal(panel.hidden,false);
  await t.live.refresh();assert.equal(card.querySelector('a'),link);assert.equal(panel.hidden,false);assert.equal(card.hidden,false);
  t.live.toggleMode('energy');assert.equal(card.querySelector('a'),null);t.live.toggleMode('energy');assert.equal(card.querySelector('a'),link);
 }finally{t.cleanup();}
});
let failed=0;for(const[n,f]of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} mode key checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
