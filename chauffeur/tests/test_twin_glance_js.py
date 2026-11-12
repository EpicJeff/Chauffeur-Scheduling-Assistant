"""One glance bar through real live pushes, custom ordering and a live remount."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const glanceModule = await import(file('static/twin/live/glance.js'));
const {mountGlance,glanceValue,formatGlanceValue,migrateGlanceTiles,buildGlanceTile,humanise} = glanceModule;
const {GLANCE_ICONS,glanceIcon} = await import(file('static/twin/live/glance_icons.js'));
const {LUCIDE} = await import(file('static/vendor/lucide/icons.js'));
const {weatherConditionIcon,renderIdleWeather} = await import(file('static/twin/live/idle.js'));
const tiles=(...ids)=>ids.map(entity=>({entity,icon:'gauge',label:''}));
const checks = [], check = (name,fn)=>checks.push([name,fn]);
const sources=[];
globalThis.EventSource = class {constructor(){sources.push(this);} close(){this.closed=true;}};
const state = (v, a={})=>({state:String(v),attributes:a});
check('no default list exists and missing preferences never invent tiles',async()=>{
  assert.equal('defaultEntities' in glanceModule,false);
  const f=await rig({devices:[{device_id:'solar',name:'Solar',kind:'sensor',entity_id:'sensor.solar',state:'5800',attributes:{device_class:'power',unit_of_measurement:'W'}}]});
  const home=document.createElement('div');document.body.append(home);const g=mountGlance(home);
  try {g.attach(f.live);assert.equal(g.bar.hidden,true);g.configure(null);assert.equal(g.bar.hidden,true);assert.equal(g.bar.children.length,0);}
  finally {g.stop();f.cleanup();home.remove();}
});
check('old lists migrate only their entities with kind or device class icons and empty labels',()=>{
  assert.deepEqual(migrateGlanceTiles(['sensor.b','climate.k','binary_sensor.d','sensor.other'],{'sensor.b':state(72,{device_class:'battery'}),'binary_sensor.d':state('on',{device_class:'door'})}),
    [{entity:'sensor.b',icon:'battery',label:''},{entity:'climate.k',icon:'thermometer',label:''},{entity:'binary_sensor.d',icon:'door',label:''},{entity:'sensor.other',icon:'gauge',label:''}]);
  assert.deepEqual(migrateGlanceTiles(null),[]);assert.deepEqual(migrateGlanceTiles([]),[]);
  assert.deepEqual(migrateGlanceTiles([{entity:'sensor.b',icon:'car',label:'EV'}]),[{entity:'sensor.b',icon:'car',label:'EV'}]);
});
check('forty selectable icons render licensed inline stroke geometry and fixed tints',()=>{
  assert.equal(Object.keys(GLANCE_ICONS).length,40);
  for(const [id,item] of Object.entries(GLANCE_ICONS)) {
    const icon=glanceIcon(id);assert.equal(icon.localName,'svg');assert.equal(icon.getAttribute('stroke'),item.color);
    assert.equal(icon.getAttribute('fill'),'none');assert.equal(icon.getAttribute('aria-hidden'),'true');
    assert.ok(LUCIDE[item.shape].length);assert.equal(icon.children.length,LUCIDE[item.shape].length);
  }
});
check('tile builder renders chosen icon value and label only when supplied',()=>{
  const cell=buildGlanceTile({entity:'sensor.p',icon:'solar',label:'Solar'});
  assert.equal(cell.dataset.entity,'sensor.p');assert.equal(cell.querySelector('svg').dataset.glanceIcon,'solar');
  assert.ok(cell.querySelector('[data-glance-value]'));assert.equal(cell.querySelector('small').textContent,'Solar');
  assert.equal(buildGlanceTile({entity:'sensor.p',icon:'house'}).querySelector('small'),null);
});
check('percentages round to whole values for battery humidity and any percent unit',()=>{
  for(const [value,a,expected] of [[99.9,{device_class:'battery'},'100 %'],[43.6,{device_class:'humidity'},'44 %'],[63.2,{unit_of_measurement:'%'},'63 %'],[0,{unit_of_measurement:'%'},'0 %']])
    assert.equal(formatGlanceValue({entity_id:'sensor.x',...state(value,a)}),expected);
  assert.equal(formatGlanceValue({entity:'sensor.x',icon:'battery'},{'sensor.x':state(99.9,{unit_of_measurement:'%'})}),'100 %');
});
check('temperature rounds whole degrees and respects entity then household units',()=>{
  const c={'sensor.temp':state(21,{device_class:'temperature',unit_of_measurement:'°C'})};
  assert.equal(glanceValue('sensor.t',state(72.7,{unit_of_measurement:'°F'})),'73 °F');
  assert.equal(glanceValue('sensor.t',state(21.6,{device_class:'temperature'}),false,c),'22 °C');
  assert.equal(glanceValue('climate.t',state('heat',{current_temperature:20.6}),false,c),'21 °C');
  assert.equal(glanceValue('weather.home',state('sunny',{temperature:73.6,temperature_unit:'°F'})),'74 °F');
});
check('binary sensors use device class words for each side',()=>{
  const words={door:['Closed','Open'],window:['Closed','Open'],garage_door:['Closed','Open'],lock:['Locked','Unlocked'],
    motion:['Clear','Detected'],occupancy:['Clear','Detected'],smoke:['Clear','Detected'],moisture:['Dry','Wet'],
    connectivity:['Disconnected','Connected'],battery:['Normal','Low'],battery_charging:['Not charging','Charging'],
    presence:['Away','Home'],problem:['OK','Problem'],safety:['Safe','Unsafe'],plug:['Unplugged','Plugged in']};
  for(const [dc,pair] of Object.entries(words)) for(const [i,v] of ['off','on'].entries())
    assert.equal(glanceValue('binary_sensor.x',state(v,{device_class:dc})),pair[i],dc);
  assert.equal(glanceValue('binary_sensor.x',state('on')),'On');
});
check('lock cover and other text humanise state words',()=>{
  for(const [id,v,expected] of [['lock.x','locking','Locking'],['lock.x','unlocked','Unlocked'],['cover.x','opening','Opening'],['cover.x','closed','Closed'],['sensor.x','partlycloudy','Partly cloudy'],['sensor.x','ready_to_go','Ready to go']])
    assert.equal(glanceValue(id,state(v)),expected);
});
check('other numeric values trim zeros and keep units with at most one decimal',()=>{
  for(const [v,u,expected] of [[1.234,'m³','1.2 m³'],[4.01,'lx','4 lx'],[-2.55,'A','-2.5 A'],[0,'','0']])
    assert.equal(glanceValue('sensor.x',state(v,{unit_of_measurement:u})),expected);
});
check('unavailable missing stale and empty readings show an em dash',()=>{
  for(const v of ['unavailable','unknown','']) assert.equal(glanceValue('sensor.x',state(v)),'—');
  assert.equal(formatGlanceValue(null),'—');assert.equal(glanceValue('sensor.x',null),'—');
  assert.equal(glanceValue('sensor.x',state(10),true),'—');
});
check('every HA weather condition has an icon and humanised words',()=>{
  const icons={sunny:'sun','clear-night':'moon',partlycloudy:'cloud-sun',cloudy:'cloud',rainy:'cloud-rain',pouring:'cloud-rain-wind',snowy:'cloud-snow','snowy-rainy':'cloud-snow',fog:'cloud-fog',windy:'wind','windy-variant':'wind',lightning:'cloud-lightning','lightning-rainy':'cloud-lightning',hail:'cloud-drizzle',exceptional:'cloud'};
  for(const [condition,icon] of Object.entries(icons)){assert.equal(weatherConditionIcon(condition),icon);assert.ok(LUCIDE[icon]);assert.ok(humanise(condition));}
  assert.equal(humanise('partlycloudy'),'Partly cloudy');assert.equal(humanise('clear-night'),'Clear night');
  assert.equal(humanise('ready_to_go'),'Ready to go');assert.equal(weatherConditionIcon('other'),'cloud');
});
check('idle weather follows household entity keeps current-only values and empties without HA',()=>{
  const host=document.createElement('div'),states={'weather.first':state('rainy',{temperature:3,temperature_unit:'°C'}),'weather.chosen':state('partlycloudy',{temperature:72.6,temperature_unit:'°F',forecast:[{temperature:100,templow:1}]})};
  renderIdleWeather(host,states,'weather.chosen');assert.equal(host.hidden,false);
  assert.equal(host.querySelector('svg').dataset.glanceIcon,'cloud-sun');assert.equal(host.querySelector('strong').textContent,'73 °F');
  assert.equal(host.querySelector('small').textContent,'Partly cloudy');assert.doesNotMatch(host.textContent,/100/);
  renderIdleWeather(host,states,null);assert.equal(host.querySelector('strong').textContent,'73 °F','same alphabetical fallback as ha_api.get_entities');
  renderIdleWeather(host,states,'weather.missing');assert.equal(host.hidden,true);
  renderIdleWeather(host,states,'weather.chosen',true);assert.equal(host.hidden,true);
  renderIdleWeather(host,{},null);assert.equal(host.hidden,true);assert.equal(host.children.length,0);
});
check('power and energy readings use one-decimal kilo units and preserve unknown direction signs',()=>{
  for (const [v,unit,expected] of [[250.4,'W','250 W'],[4000,'W','4.0 kW'],[-2000,'W','-2.0 kW'],[999,'W','999 W'],[1000,'W','1.0 kW'],
    [4,'kW','4.0 kW'],[-.5,'kW','-500 W'],[1500,'Wh','1.5 kWh'],[4,'kWh','4.0 kWh'],[-2500,'Wh','-2.5 kWh'],[2,'MWh','2000.0 kWh']])
    assert.equal(glanceValue('sensor.reading',state(v,{unit_of_measurement:unit})),expected);
  assert.equal(glanceValue('sensor.reading',state('unavailable',{unit_of_measurement:'W'})),'—');
  assert.equal(glanceValue('sensor.reading',state(4000,{unit_of_measurement:'W'}),true),'—');
});
check('energy uses whole Wh below one thousand and one decimal kWh above it without direction words',()=>{
  for(const [v,unit,expected] of [[250.4,'Wh','250 Wh'],[999,'Wh','999 Wh'],[1000,'Wh','1.0 kWh'],[-1500,'Wh','-1.5 kWh'],[2.345,'kWh','2.3 kWh'],[2,'MWh','2000.0 kWh']])
    assert.equal(glanceValue('sensor.grid',state(v,{unit_of_measurement:unit}),false,{}, {grid_power:'sensor.grid'}),expected);
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
    g.attach(fixture.live);g.configure(tiles('sensor.battery'));assert.equal(g.bar.querySelector('strong').textContent,'charging 2.0 kW');
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
  glance=mountGlance(home);t.view.glance=glance;glance.attach(t.live);glance.configure([{entity:'sensor.power',icon:'solar',label:'Roof'},...tiles('sensor.temp','climate.kitchen')]);
  assert.deepEqual([...glance.bar.children].map(n=>n.dataset.entity),['sensor.power','sensor.temp','climate.kitchen']);
  assert.match(glance.bar.textContent,/1.2 kW/);
  assert.equal(glance.bar.children[2].querySelector('strong').textContent,'71 °F');
  assert.equal(glance.bar.children[0].querySelector('svg').dataset.glanceIcon,'solar');
  assert.equal(glance.bar.children[0].querySelector('small').textContent,'Roof');
  assert.equal(glance.bar.children[0].querySelector('[data-glance-unit]').textContent,'kW');
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
  glance.configure([]);assert.equal(glance.bar.hidden,true);glance.configure(null);assert.equal(glance.bar.hidden,true);
  t.cleanup();assert.equal(glance.bar.hidden,true);
  const next=await rig({devices:[{device_id:'p',name:'Power',kind:'sensor',entity_id:'sensor.p',state:'3',attributes:{device_class:'power'}}]});
  glance.attach(next.live);glance.configure(tiles('sensor.p'));assert.equal(document.querySelectorAll('#twin-glance').length,1);assert.match(glance.bar.textContent,/3/);
  next.cleanup();glance.stop();assert.equal(document.querySelectorAll('#twin-glance').length,0);
});
check('settings entry loads linked choices searches reorders removes saves and inherits',async()=>{
  const {mountGlanceSettings}=await import(file('static/twin/live/glance_settings.js'));
  const make=(id,tag='div',parent=document.body)=>{const n=document.createElement(tag);n.id=id;parent.append(n);return n;};
  const editor=make('twin-glance-settings'),picker=make('twin-glance-panel','select',editor);picker.value='';
  const source=make('twin-glance-source','select',editor);source.options=[document.createElement('option'),document.createElement('option')];
  const search=make('twin-glance-search','input',editor);search.value='';
  const selected=make('twin-glance-selected','ol',editor),choices=make('twin-glance-choices','div',editor);
  make('twin-glance-icons','div',editor);make('twin-glance-entity-picker','div',editor);const add=make('twin-glance-add','button',editor);
  const cancel=make('twin-glance-cancel','button',editor);make('twin-glance-empty','p',editor);
  make('house_twin_idle_enabled','input',editor);make('twin-panels-idle','input',make('idle-label','label',editor));
  const save=make('twin-glance-save','button',editor);make('twin-settings-gear','button');
  const fixture=await rig({devices:[{device_id:'a',name:'A',kind:'sensor',entity_id:'sensor.a',state:'1'},
    {device_id:'c',name:'C',kind:'sensor',entity_id:'sensor.c',state:'3'},
    {device_id:'b',name:'B',kind:'sensor',entity_id:'sensor.b',state:'2'}]});
  const prefs={can_edit:true,entities:tiles('sensor.a','sensor.b'),household_entities:tiles('sensor.a','sensor.b'),panel_entities:null,
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
    await press(selected.children[1].querySelector('[data-action="up"]'));
    assert.match(selected.children[0].textContent,/sensor.b/);
    await press(selected.children[1].querySelectorAll('button')[4]);assert.equal(selected.children.length,1);
    await press(add);search.value='sensor.a';search.dispatchEvent(new Event('input'));assert.equal(choices.children.length,1);
    await press(choices.children[0]);
    const grid=document.getElementById('twin-glance-icons');assert.equal(grid.children.length,40);assert.equal(save.disabled,true);
    await press(grid.children[0]);
    const label=selected.children[1].querySelector('input');label.value='Roof';label.dispatchEvent(new Event('input'));
    await press(save);assert.deepEqual(sent.entities,[...tiles('sensor.b'),{entity:'sensor.a',icon:'solar',label:'Roof'}]);assert.equal(status.at(-1),true);
    await press(selected.children[1].querySelector('[data-action="icon"]'));await press(grid.children[4]);
    assert.equal(selected.children[1].querySelector('svg').dataset.glanceIcon,'car');
    assert.equal(selected.children[1].querySelector('input').value,'Roof','changing icon keeps the label');
    await press(selected.children[1].querySelector('[data-action="entity"]'));
    search.value='sensor.c';search.dispatchEvent(new Event('input'));await press(choices.children[0]);
    await press(save);assert.deepEqual(sent.entities,[...tiles('sensor.b'),{entity:'sensor.c',icon:'car',label:'Roof'}]);
    await press(add);assert.equal(document.activeElement,search);await press(cancel);
    assert.equal(selected.children.length,2);assert.equal(document.activeElement,add,'cancel restores keyboard focus');
    await press(selected.children[1].querySelector('[data-action="icon"]'));
    editor.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
    assert.equal(grid.hidden,true);assert.equal(selected.children[1].querySelector('svg').dataset.glanceIcon,'car','Escape cancels without changes');
    picker.value='kitchen';picker.dispatchEvent(new Event('change'));await wait(40);
    assert.equal(source.value,'inherit');assert.equal(source.options[0].textContent,'Use household tiles');
    assert.equal(selected.children[0].querySelector('input').disabled,true,'inherited household tiles are visible and read only');
    await press(save);assert.equal(sent.panel_id,'kitchen');assert.equal(sent.entities,null);
    source.value='custom';source.dispatchEvent(new Event('change'));
    const panelLabel=selected.children[0].querySelector('input');panelLabel.value='Panel only';panelLabel.dispatchEvent(new Event('input'));
    await press(save);assert.equal(sent.entities[0].label,'Panel only');assert.equal(prefs.household_entities[0].label,'','panel editing keeps household choices');
    picker.value='hall';picker.dispatchEvent(new Event('change'));await wait(10);assert.equal(save.disabled,true);
    picker.value='kitchen';picker.dispatchEvent(new Event('change'));await wait(20);
    releaseLate();await wait(20);assert.equal(source.value,'inherit');assert.equal(selected.children.length,2,'late response never overwrites the current panel');
  }finally{settings.stop();fixture.cleanup();editor.remove();}
});
check('a chosen unplaced sensor starts a scoped stream and updates on push',async()=>{
  const fixture=await rig({devices:[]}),home=document.createElement('div');document.body.append(home);
  const g=mountGlance(home);
  try {
    g.attach(fixture.live);const previous=sources.at(-1);g.configure([{entity:'sensor.unusual',icon:'gauge'}]);
    assert.equal(previous.closed,true,'selection reconnects the server-owned scope');
    const stream=sources.at(-1);assert.notEqual(stream,previous);
    stream.onmessage({data:JSON.stringify({entity_id:'sensor.unusual',state:state(12.34,{unit_of_measurement:'V'})})});
    await wait(40);assert.equal(g.bar.querySelector('strong').textContent,'12.3 V');
    g.configure([{entity:'sensor.unusual',icon:'car',label:'Voltage'}]);assert.equal(sources.at(-1),stream,'presentation changes do not reconnect');
  } finally {g.stop();fixture.cleanup();home.remove();}
});
let failed=0;
for(const [name,fn] of checks){try{await fn();console.log('  ok  '+name);}catch(e){failed++;console.log('  FAIL '+name+' '+e.stack);}}
glance?.stop();t?.cleanup();assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} glance checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
