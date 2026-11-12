"""One glance bar through real live pushes, custom ordering and a live remount."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {defaultEntities,mountGlance,glanceValue} = await import(file('static/twin/live/glance.js'));
const checks = [], check = (name,fn)=>checks.push([name,fn]);
const sources=[];
globalThis.EventSource = class {constructor(){sources.push(this);} close(){this.closed=true;}};
const state = (v, a={})=>({state:String(v),attributes:a});
check('defaults weather then at most four energy readings in state order',()=>{
  const states={'sensor.other':state(1),'weather.home':state('sunny',{temperature:73,temperature_unit:'°F'}),
    'sensor.solar':state(3.2,{unit_of_measurement:'kW'}),'sensor.powerwall':state(74),
    'sensor.grid':state(1),'sensor.car_charging':state(32),'sensor.fifth':state(5,{device_class:'power'})};
  assert.deepEqual(defaultEntities(states),['weather.home','sensor.solar','sensor.powerwall','sensor.grid','sensor.car_charging']);
  assert.deepEqual(defaultEntities({}),[]); assert.deepEqual(defaultEntities({'weather.x':state('sunny')}),[]);
  assert.equal(glanceValue('weather.home',states['weather.home']),'73 °F');
});
check('power and energy readings use one-decimal kilo units and preserve unknown direction signs',()=>{
  for (const [v,unit,expected] of [[4000,'W','4.0 kW'],[-2000,'W','-2.0 kW'],[999,'W','999 W'],[1000,'W','1.0 kW'],
    [4,'kW','4.0 kW'],[-.5,'kW','-500 W'],[1500,'Wh','1.5 kWh'],[4,'kWh','4.0 kWh'],[-2500,'Wh','-2.5 kWh'],[2,'MWh','2000.0 kWh']])
    assert.equal(glanceValue('sensor.reading',state(v,{unit_of_measurement:unit})),expected);
  assert.equal(glanceValue('sensor.reading',state('unavailable',{unit_of_measurement:'W'})),'—');
  assert.equal(glanceValue('sensor.reading',state(4000,{unit_of_measurement:'W'}),true),'—');
});
check('mapped battery and grid signs become charging/discharging/importing/exporting words',()=>{
  const m={battery_power:'sensor.battery',grid_power:'sensor.grid'};
  const value=(id,v,map=m)=>glanceValue(id,state(v,{unit_of_measurement:'W'}),false,{},map);
  assert.equal(value('sensor.battery',-2000),'charging 2.0 kW');assert.equal(value('sensor.battery',2000),'discharging 2.0 kW');
  assert.equal(value('sensor.grid',-1500),'exporting 1.5 kW');assert.equal(value('sensor.grid',1500),'importing 1.5 kW');
  assert.equal(value('sensor.battery',2000,{...m,battery_positive:'charge'}),'charging 2.0 kW');
  assert.equal(value('sensor.grid',1500,{...m,grid_positive:'export'}),'exporting 1.5 kW');
  assert.equal(value('sensor.battery',0),'0 W');assert.equal(value('sensor.unknown',-2000),'-2.0 kW');
});
check('mounted glance uses the live mapping and updates direction words after a push',async()=>{
  const fixture=await rig({devices:[{device_id:'battery',name:'Battery',kind:'sensor',entity_id:'sensor.battery',state:'-2000',attributes:{device_class:'power',unit_of_measurement:'W'}}]});
  const home=document.createElement('div');document.body.append(home);const g=mountGlance(home);fixture.view.glance=g;
  try{
    g.attach(fixture.live);g.configure(['sensor.battery']);assert.equal(g.bar.querySelector('strong').textContent,'charging 2.0 kW');
    fixture.live.configureEnergy({mapping:{battery_power:'sensor.battery',battery_positive:'charge'},cars:[]});
    assert.equal(g.bar.querySelector('strong').textContent,'discharging 2.0 kW');
    sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.battery',state:state(2000,{device_class:'power',unit_of_measurement:'W'})})});
    await wait(40);assert.equal(g.bar.querySelector('strong').textContent,'charging 2.0 kW');
  }finally{g.stop();fixture.cleanup();home.remove();}
});
check('climate shows the current temperature before the target or mode',()=>{
  assert.equal(glanceValue('climate.kitchen',state('heat',{current_temperature:71,temperature:68,unit_of_measurement:'°F'})),'71 °F');
  assert.equal(glanceValue('climate.kitchen',state('off',{current_temperature:0,temperature:20,unit_of_measurement:'°C'})),'0 °C');
  assert.equal(glanceValue('climate.kitchen',state('heat',{temperature:68,unit_of_measurement:'°F'})),'68 °F');
  assert.equal(glanceValue('climate.kitchen',state('heat_cool',{current_temperature:'unknown',target_temp_low:68,target_temp_high:74,unit_of_measurement:'°F'})),'68–74 °F');
  assert.equal(glanceValue('climate.kitchen',state('heat',{current_temperature:'',temperature:null,unit_of_measurement:'°F'})),'—');
  assert.equal(glanceValue('climate.kitchen',state('unavailable',{current_temperature:71,unit_of_measurement:'°F'})),'—');
  assert.equal(glanceValue('climate.kitchen',state('heat',{current_temperature:71}),true),'—');
});
check('water heater and humidifier use current readings then targets then em dash',()=>{
  assert.equal(glanceValue('water_heater.tank',state('eco',{current_temperature:120,temperature:125,unit_of_measurement:'°F'})),'120 °F');
  assert.equal(glanceValue('water_heater.tank',state('eco',{temperature:125,unit_of_measurement:'°F'})),'125 °F');
  assert.equal(glanceValue('water_heater.tank',state('eco')),'—');
  assert.equal(glanceValue('humidifier.room',state('on',{current_humidity:43,humidity:50,unit_of_measurement:'wrong'})),'43 %');
  assert.equal(glanceValue('humidifier.room',state('off',{current_humidity:0,humidity:50})),'0 %');
  assert.equal(glanceValue('humidifier.room',state('on',{current_humidity:'unknown',humidity:50})),'50 %');
  assert.equal(glanceValue('humidifier.room',state('on',{current_humidity:null})),'—');
});
check('bottom clearance follows actual orb and desktop chat geometry and survives idle moves',()=>{
  const home=document.createElement('div'),card=document.createElement('div');document.body.append(home,card);
  const orb=document.createElement('button');orb.id='panel-chat-orb';orb._rect={left:668,top:830,width:64,height:64};
  const chat=document.createElement('div');chat.id='chat-overlay-container';chat._rect={left:364,top:900,width:672,height:60};
  document.body.append(orb,chat);
  const observers=[],original=window.ResizeObserver;
  window.ResizeObserver=class{constructor(fn){this.notify=fn;this.observed=[];observers.push(this);}observe(n){this.observed.push(n);}disconnect(){this.disconnected=true;}};
  const g=mountGlance(home);
  try {
    assert.equal(home.style.getPropertyValue('--twin-glance-clearance'),'182px');
    assert.ok(observers[0].observed.includes(orb));assert.ok(observers[0].observed.includes(chat));
    orb._rect.top=800;observers[0].notify();assert.equal(home.style.getPropertyValue('--twin-glance-clearance'),'212px');
    orb.hidden=true;chat._rect.top=850;window.dispatchEvent(new Event('resize'));
    assert.equal(home.style.getPropertyValue('--twin-glance-clearance'),'162px');
    const bar=g.bar;g.move(card);assert.equal(bar.parentElement,card);g.move(home);assert.equal(g.bar,bar);
    chat.hidden=true;g.update();assert.equal(home.style.getPropertyValue('--twin-glance-clearance'),'0px');
    g.stop();assert.equal(observers[0].disconnected,true);
    chat.hidden=false;window.dispatchEvent(new Event('resize'));assert.equal(home.style.getPropertyValue('--twin-glance-clearance'),'0px');
  } finally {g.stop();window.ResizeObserver=original;orb.remove();chat.remove();home.remove();card.remove();}
});
let t, glance;
check('configured entities render in order and secondary sensor updates by stream',async()=>{
  t=await rig({devices:[{device_id:'temp',name:'Temp',kind:'sensor',entity_id:'sensor.temp',state:'70',attributes:{unit_of_measurement:'°F'}},
    {device_id:'power',name:'Power',kind:'sensor',entity_id:'sensor.power',state:'1.2',attributes:{device_class:'power',unit_of_measurement:'kW'}},
    {device_id:'thermostat',name:'Thermostat',kind:'climate',entity_id:'climate.kitchen',state:'heat',attributes:{current_temperature:71,temperature:68,unit_of_measurement:'°F'}}]});
  const home=document.createElement('div');home.id='twin-glance-home';document.body.append(home);
  glance=mountGlance(home);t.view.glance=glance;glance.attach(t.live);glance.configure(['sensor.power','sensor.temp','climate.kitchen']);
  assert.deepEqual([...glance.bar.children].map(n=>n.dataset.entity),['sensor.power','sensor.temp','climate.kitchen']);
  assert.match(glance.bar.textContent,/1.2 kW/);
  assert.equal(glance.bar.children[2].querySelector('strong').textContent,'71 °F');
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.power',state:state('4.5',{unit_of_measurement:'kW'})})});
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'climate.kitchen',state:state('heat',{current_temperature:72,temperature:68,unit_of_measurement:'°F'})})});
  await wait(40);assert.match(glance.bar.textContent,/4.5 kW/);
  assert.equal(glance.bar.children[2].querySelector('strong').textContent,'72 °F');
});
check('unavailable and removed values show em dash',async()=>{
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.power',state:state('unavailable')})});
  await wait(40);assert.equal(glance.bar.children[0].querySelector('strong').textContent,'—');
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.temp',state:null})});
  await wait(40);assert.equal(glance.bar.children[1].querySelector('strong').textContent,'—');
});
check('idle moves the same bar and preserves its cells and stream listener',async()=>{
  const card=document.createElement('div');card.id='twin-idle-clock';document.body.append(card);
  const bar=glance.bar,cell=bar.children[0];glance.move(card);
  assert.equal(document.querySelectorAll('#twin-glance').length,1);assert.equal(bar.parentElement,card);assert.equal(bar.children[0],cell);
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.power',state:state(6,{unit_of_measurement:'kW'})})});
  await wait(40);assert.match(bar.textContent,/6\.0 kW/);
  glance.move(document.getElementById('twin-glance-home'));assert.equal(glance.bar,bar);
});
check('empty list hides and remount attaches once without duplicating bar',async()=>{
  sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.power',state:state(6,{device_class:'power',unit_of_measurement:'kW'})})});await wait(40);
  glance.configure([]);assert.equal(glance.bar.hidden,true);glance.configure(null);assert.equal(glance.bar.hidden,false);
  t.cleanup();assert.equal(glance.bar.hidden,true);
  const next=await rig({devices:[{device_id:'p',name:'Power',kind:'sensor',entity_id:'sensor.p',state:'3',attributes:{device_class:'power'}}]});
  glance.attach(next.live);assert.equal(document.querySelectorAll('#twin-glance').length,1);assert.match(glance.bar.textContent,/3/);
  next.cleanup();glance.stop();assert.equal(document.querySelectorAll('#twin-glance').length,0);
});
check('settings entry loads linked choices searches reorders removes saves and inherits',async()=>{
  const {mountGlanceSettings}=await import(file('static/twin/live/glance_settings.js'));
  const make=(id,tag='div',parent=document.body)=>{const n=document.createElement(tag);n.id=id;parent.append(n);return n;};
  const editor=make('twin-glance-settings'),picker=make('twin-glance-panel','select',editor);picker.value='';
  const source=make('twin-glance-source','select',editor);source.options=[document.createElement('option'),document.createElement('option')];
  const search=make('twin-glance-search','input',editor);search.value='';
  const selected=make('twin-glance-selected','ol',editor),choices=make('twin-glance-choices','div',editor);
  make('house_twin_idle_enabled','input',editor);make('twin-panels-idle','input',make('idle-label','label',editor));
  const save=make('twin-glance-save','button',editor);make('twin-settings-gear','button');
  const fixture=await rig({devices:[{device_id:'a',name:'A',kind:'sensor',entity_id:'sensor.a',state:'1'},
    {device_id:'b',name:'B',kind:'sensor',entity_id:'sensor.b',state:'2'}]});
  const prefs={can_edit:true,entities:['sensor.a','sensor.b'],household_entities:['sensor.a','sensor.b'],panel_entities:null,
    idle_enabled:false,panel_idle_enabled:true,panels:[{device_id:'kitchen',label:'Kitchen'}]};
  let sent,releaseLate;
  const api=async(path,init)=>{
    if(init){sent=JSON.parse(init.body);return{ok:true};}
    if(path.includes('panel_id=hall')) {await new Promise(r=>releaseLate=r);return{ok:true,json:async()=>({...prefs,panel_entities:['sensor.stale']})};}
    return{ok:true,json:async()=>structuredClone(prefs)};
  };
  const status=[];window.chfSettingsSaved=(ok)=>status.push(ok);
  const settings=mountGlanceSettings(fixture.view,{configure(){}},{configure(){}},{api});
  try{
    await wait(50);assert.equal(selected.children.length,2);
    await press(selected.children[1].querySelectorAll('button')[0]);
    assert.match(selected.children[0].textContent,/sensor.b/);
    await press(selected.children[1].querySelectorAll('button')[2]);assert.equal(selected.children.length,1);
    search.value='sensor.a';search.dispatchEvent(new Event('input'));assert.equal(choices.children.length,1);
    await press(choices.children[0]);await press(save);assert.deepEqual(sent.entities,['sensor.b','sensor.a']);assert.equal(status.at(-1),true);
    picker.value='kitchen';picker.dispatchEvent(new Event('change'));await wait(40);
    assert.equal(source.value,'inherit');assert.equal(source.options[0].textContent,'Use household list');
    await press(save);assert.equal(sent.panel_id,'kitchen');assert.equal(sent.entities,null);
    picker.value='hall';picker.dispatchEvent(new Event('change'));await wait(10);assert.equal(save.disabled,true);
    picker.value='kitchen';picker.dispatchEvent(new Event('change'));await wait(20);
    releaseLate();await wait(20);assert.equal(source.value,'inherit');assert.equal(selected.children.length,0,'late response never overwrites the current panel');
  }finally{settings.stop();fixture.cleanup();editor.remove();}
});
let failed=0;
for(const [name,fn] of checks){try{await fn();console.log('  ok  '+name);}catch(e){failed++;console.log('  FAIL '+name+' '+e.stack);}}
glance?.stop();t?.cleanup();assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} glance checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
