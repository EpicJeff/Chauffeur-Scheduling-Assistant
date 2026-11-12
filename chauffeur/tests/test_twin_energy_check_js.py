"""Energy check role states and the mounted drawer/legend/ribbon contract."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {energyCheck,renderEnergyCheck}=await import(file('static/twin/live/energy_check.js'));
const {guessEnergy}=await import(file('static/twin/live/energy_mapping.js'));
const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
const checks=[],check=(name,f)=>checks.push([name,f]);
const power=state=>({state:String(state),attributes:{device_class:'power',unit_of_measurement:'W'}});
function fixture(){
 const keys=['solar','battery','grid','house','ev'];
 const b={id:'b',name:'Home',position:[0,0],levels:[{id:'L1',name:'Ground floor',elevation:0}],walls:[],anchors:[],
  roof:{sections:[{id:'roof',kind:'flat',rect:[-40,-10,40,20],pitch:0,plate:10,overhang:0,level:'L1'}]},
  solar_zones:[{id:'z',roof:'roof',plane:[0,0,10],rect:[-30,-5,-10,5]}]};
 const view={plan:{buildings:[b]}},mapping={solar_power:'sensor.solar_power',battery_power:'sensor.battery_power',grid_power:'sensor.grid_power',house_power:'sensor.house_power',cars:[{id:'ev',name:'Family EV'}],chargers:[{id:'evse',name:'Family EV charger',power:'sensor.ev_power'}]};
 const states=Object.fromEntries(keys.map(k=>['sensor.'+k+'_power',power(k==='solar'?4000:k==='house'?2000:k==='battery'?-1000:k==='grid'?-1000:49)]));
 const layout={markers:keys.slice(1).map((k,i)=>({device_id:k,name:k==='battery'?'Powerwall':k,entity_id:'sensor.'+k+'_power',entities:[],placed:true,location_valid:true,building:'b',level:'L1',at:[i*8,0,3]}))};
 return {view,mapping,states,layout};
}
const assess=f=>energyCheck(f.view,f.layout,f.mapping,f.states);
check('a dedicated fuel car is an explained setup error in the shared Energy check',()=>{
 const f=fixture();f.mapping.cars=[{id:'gls',name:'Mercedes GLS',fuel_level:'sensor.gls_fuel_level'}];
 f.mapping.chargers[0].car='gls';
 const report=assess(f),row=report.roles.find(r=>r.id==='charger:0');
 assert.equal(row.car,null);assert.equal(row.status,'invalid');
 assert.ok(row.state.includes('Mercedes GLS has no battery reading; a charger can only charge an electric car'));
 const host=document.createElement('div');renderEnergyCheck(host,report);
 assert.equal(host.querySelector('[data-energy-role="charger:0"] [data-energy-mark]').dataset.energyMark,'warning');
 assert.ok(host.textContent.includes(row.reason));
});
const entityKey=id=>id==='charger:0'?'power':id+'_power';
for(const id of ['solar','battery','grid','house','charger:0'])for(const scenario of ['unset','unavailable','unplaced','ok'])check(id+' '+scenario,()=>{
 const f=fixture(),object=id==='charger:0'?f.mapping.chargers[0]:f.mapping,key=entityKey(id),entity=object[key];
 if(scenario==='unset')object[key]=null;
 if(scenario==='unavailable')f.states[entity].state='unavailable';
 if(scenario==='unplaced'){
  if(id==='solar')f.view.plan.buildings[0].solar_zones=[];
  else f.layout.markers=f.layout.markers.filter(m=>m.entity_id!==entity);
 }
 const row=assess(f).roles.find(r=>r.id===id);assert.equal(row.status,scenario);
 assert.equal(row.symbol,scenario==='ok'?'✓':scenario==='unavailable'?'⚠':'✗');
 if(scenario==='unset')assert.equal(row.power,'not set: choose it above');
 else assert.ok(row.power.includes(entity));
 if(scenario==='unavailable')assert.ok(row.state.startsWith('unavailable'));
 if(scenario==='unplaced')assert.ok(row.location.includes(id==='solar'?'add a solar zone':entity));
 if(scenario==='ok')assert.ok(row.location.includes(id==='solar'?'solar zone on roof of Home (source)':'Ground floor'));
});
for(const id of ['battery','grid','house','charger:0'])check(id+' placed under another entity',()=>{
 const f=fixture(),entity=(id==='charger:0'?f.mapping.chargers[0].power:f.mapping[id+'_power']);
 const m=f.layout.markers.find(m=>m.entity_id===entity);m.entity_id=entity.replace(/_power$/,'_charge');
 const row=assess(f).roles.find(r=>r.id===id);assert.equal(row.status,'unplaced');
 assert.ok(row.location.includes('is placed via '+m.entity_id));assert.ok(row.location.includes('role uses '+entity));
});
check('a placed device exposing the power entity is valid even with a different primary entity',()=>{
 const f=fixture(),m=f.layout.markers[0];m.entities=[m.entity_id];m.entity_id='sensor.powerwall_charge';
 assert.equal(assess(f).roles.find(r=>r.id==='battery').status,'ok');
});
check('solar zone readings and both signs use the existing glance formatter',()=>{
 const f=fixture();f.mapping.solar_power=null;f.view.plan.buildings[0].solar_zones[0].entity='sensor.zone';f.states['sensor.zone']=power(4000);
 const r=assess(f).roles;assert.equal(r[0].status,'ok');assert.equal(r[0].power,'sensor.zone: 4.0 kW');
 assert.equal(r[1].power,'sensor.battery_power: charging 1.0 kW');assert.equal(r[2].power,'sensor.grid_power: exporting 1.0 kW');
 f.mapping.battery_positive='charge';f.mapping.grid_positive='export';const next=assess(f).roles;
 assert.equal(next[1].sign,'positive = charging');assert.equal(next[2].sign,'positive = exporting');
 assert.ok(next[1].power.includes('discharging'));assert.ok(next[2].power.includes('importing'));
});
check('missing live state, invalid reading and stale feed are explicit',()=>{
 const f=fixture();delete f.states[f.mapping.battery_power];assert.equal(assess(f).roles[1].state,'unavailable');
 f.states[f.mapping.battery_power]={state:'3',attributes:{unit_of_measurement:'kWh'}};
 assert.equal(assess(f).roles[1].status,'invalid');
 const stale=energyCheck(f.view,f.layout,f.mapping,f.states,true);assert.equal(stale.showing,0);
 assert.equal(stale.summary,'No ribbons because live readings are unavailable');assert.ok(stale.flows.every(r=>!r.shown));
});
check('flows preserve small allocations, threshold, missing endpoints and the summary',()=>{
 const f=fixture();let s=assess(f);assert.equal(s.summary,'Ribbons showing: 3');
 assert.deepEqual(s.flows.filter(r=>r.shown).map(r=>[r.id,r.watts]),[['solar:house',2000],['solar:battery',1000],['solar:grid',1000]]);
 assert.equal(s.flows.find(r=>r.id==='charger:0').watts,49);assert.equal(s.flows.find(r=>r.id==='charger:0').status,'hidden (under 50 W)');
 f.states['sensor.ev_power']=power(50);assert.equal(assess(f).flows.find(r=>r.id==='charger:0').status,'shown');
 f.layout.markers=f.layout.markers.filter(m=>m.device_id!=='grid');s=assess(f);
 assert.equal(s.flows.find(r=>r.id==='solar:grid').status,'no ribbon: Meter / grid not placed');
 f.states['sensor.solar_power']=power(0);f.states['sensor.house_power']=power(500);f.states['sensor.battery_power']=power(-1000);f.states['sensor.grid_power']=power(1500);f.states['sensor.ev_power']=power(0);
 s=assess(f);assert.equal(s.summary,'No ribbons because Meter / grid not placed');
 for(const id of ['grid:house','grid:battery'])assert.equal(s.flows.find(r=>r.id===id).status,'no ribbon: Meter / grid not placed');
});
check('summary explains missing power and quiet totals without blaming optional roles',()=>{
 const f=fixture();f.mapping.house_power=null;{const a=assess(f);assert.match(a.summary,/Electric panel \/ house worked out from the other three readings/);}
 f.mapping.house_power='sensor.house_power';for(const r of Object.values(f.states))r.state='0';
 f.mapping.battery_power=null;f.mapping.grid_power=null;
 assert.match(assess(f).summary,/^No ribbons because all allocated flows are under 50 W/);
 f.states['sensor.house_power'].state='unavailable';assert.equal(assess(f).summary,'No ribbons because balance unknown: Meter / grid and Electric panel / house not readable');
});
check('object locations name the wall and removed selections do not fall back',()=>{
 const f=fixture(),b=f.view.plan.buildings[0];b.name='Main House';b.levels[0].name='main floor';
 b.walls=[{id:'wall:eef4~2',exterior:true,level:'L1',from:[0,0],to:[20,0],thickness:.5}];
 b.anchors=[{id:'meter',kind:'meter',host:{wall:'wall:eef4~2',side:'right',at:4,z:4}}];
 f.mapping.locations={grid:{type:'object',id:'meter',building:'b'}};
 assert.equal(assess(f).roles[2].location,'meter object on exterior wall of Main House, main floor');
 delete b.name;assert.equal(assess(f).roles[2].location,'meter object on a wall');
 b.anchors=[];const row=assess(f).roles[2];assert.equal(row.status,'unplaced');assert.ok(row.location.includes('add a meter object'));assert.ok(row.location.includes('selected location'));
});
check('unbalanced zero house warns with its sensor and explains why no ribbons show',()=>{
 const f=fixture();for(const row of Object.values(f.states))row.state='0';
 f.states[f.mapping.grid_power]={state:'1.8',attributes:{device_class:'power',unit_of_measurement:'kW'}};
 f.mapping.house_power=f.mapping.battery_power;
 const s=assess(f),house=s.roles.find(r=>r.id==='house');
 assert.equal(house.symbol,'⚠');assert.equal(house.status,'unbalanced');
 assert.match(house.state,/readings don't balance: solar \+ battery \+ grid = 1.8 kW, house reads 0.0 kW — is the house sensor right\?/);
 assert.ok(house.state.includes('sensor.battery_power'));
 assert.equal(s.summary,"No ribbons because the readings don't balance — check the Electric panel / house sensor");
 assert.equal(s.showing,0);assert.ok(s.flows.filter(r=>!r.id.startsWith('charger:')).every(r=>r.status.includes("readings don't balance")));
 f.mapping.house_power='sensor.house_power';f.states[f.mapping.house_power].state='500';
 const partial=assess(f);assert.equal(partial.roles[3].status,'unbalanced');assert.equal(partial.summary,'Ribbons showing: 1');
 assert.deepEqual(partial.flows.filter(r=>r.shown).map(r=>[r.id,r.watts]),[['grid:house',500]]);
});
check('balanced totals and tolerance have no balance warning, including reversed signs',()=>{
 const f=fixture();assert.equal(assess(f).roles[3].status,'ok');
 f.mapping.battery_positive='charge';f.mapping.grid_positive='export';
 f.states[f.mapping.battery_power].state='1000';f.states[f.mapping.grid_power].state='1000';
 assert.equal(assess(f).roles[3].status,'ok');
 f.states[f.mapping.house_power].state='2500';assert.equal(assess(f).roles[3].status,'ok');
 f.states[f.mapping.house_power].state='2501';assert.equal(assess(f).roles[3].status,'unbalanced');
 for(const row of Object.values(f.states))row.state='0';
 f.states[f.mapping.grid_power].state='-200';assert.equal(assess(f).roles[3].status,'ok');
 f.states[f.mapping.grid_power].state='-201';assert.equal(assess(f).roles[3].status,'unbalanced');
 delete f.states[f.mapping.house_power];assert.notEqual(assess(f).roles[3].status,'unbalanced');
});
check('roof and device locations use plan names or human fallbacks, never location ids',()=>{
 const f=fixture(),b=f.view.plan.buildings[0];b.name='Pool House';
 b.roof.sections[0].id='roof:c8d9';b.solar_zones[0].roof='roof:c8d9';
 let s=assess(f);assert.equal(s.roles[0].location,'solar zone on roof of Pool House (source)');
 assert.ok(!s.roles[0].location.includes('roof:c8d9'));
 delete b.name;delete b.levels[0].name;
 s=assess(f);assert.equal(s.roles[0].location,'solar zone on a roof (source)');
 assert.ok(!s.roles[1].location.includes('L1'));assert.ok(!s.roles[1].location.includes('on b'));
});
check('renderer exposes separate status marks, bold names and flow states in both hosts',()=>{
 for(const className of ['twin-energy-check','twin-energy-check wall']){
  const host=document.createElement('div');host.className=className;
  const f=fixture();f.layout.markers=f.layout.markers.filter(m=>m.device_id!=='grid');
  renderEnergyCheck(host,assess(f));
  assert.equal(host.children[0].dataset.energySummary,'');
  const house=host.querySelector('[data-energy-role="house"]');
  assert.equal(house.querySelector('[data-energy-mark]').textContent,'✓');
  assert.equal(house.querySelector('strong').textContent,'Electric panel / house');
  assert.equal(host.querySelector('[data-energy-flow="solar:house"]').dataset.status,'shown');
  assert.equal(host.querySelector('[data-energy-flow="solar:grid"]').dataset.status,'blocked');
  assert.equal(host.querySelector('[data-energy-flow="charger:0"]').dataset.status,'hidden');
 }
});
check('mounted mode, drawer and wall link show the same decisions on pushes and clean up',async()=>{
 const f=fixture(),devices=f.layout.markers.map(m=>({...m,state:f.states[m.entity_id].state,attributes:power(0).attributes,kind:'power'}));
 devices.push({device_id:'solar',name:'Solar',entity_id:'sensor.solar_power',state:'4000',attributes:power(0).attributes,kind:'power'});
 const t=await rig({devices});let settings,opened;
 const section=document.createElement('section'),save=document.createElement('button');save.id='twin-energy-save';section.append(save);document.body.append(section);
 try{
  Object.assign(t.view.plan.buildings[0],f.view.plan.buildings[0]);t.view.plan={...t.view.plan};await t.live.refresh();
  const preferences={mapping:f.mapping,cars:[],can_edit:false};t.live.configureEnergy(preferences);t.live.setMode('energy');
  settings=mountEnergySettings(t.view,{api:async()=>({ok:true,json:async()=>preferences})});await settings.reload();
  const s=t.live.energy();assert.equal(s.check.summary,'Ribbons showing: 3');
  assert.deepEqual(s.check.flows.filter(r=>r.shown).map(r=>r.id).sort(),s.ribbons.filter(r=>r.visible).map(r=>r.id).sort());
  const legend=document.getElementById('twin-mode-legend'),link=legend.querySelector('a');
  window.chfOpenSettings=(...args)=>{opened=args;};await press(link);assert.deepEqual(opened,['twin','twin-energy-check']);delete window.chfOpenSettings;
  assert.equal(document.querySelector('#twin-energy-check [data-energy-summary]').textContent,s.check.summary);
  t.states['sensor.solar_power'].state='0';t.states['sensor.grid_power'].state='1500';t.states['sensor.house_power'].state='500';await t.live.refresh();
  assert.equal(document.querySelector('#twin-energy-check [data-energy-summary]').textContent,t.live.energy().check.summary);
  // Exercise the actual mounted diagnostic on a bad saved mapping, live pushes,
  // and its repair, alongside the same ribbons that the wall renders.
  for(const row of Object.values(t.states))if(row.attributes?.device_class==='power')row.state='0';
  t.states['sensor.grid_power'].state='1800';t.states['sensor.house_power'].state='1800';
  preferences.mapping={...f.mapping,house_power:'sensor.battery_power'};t.live.configureEnergy(preferences);await t.live.refresh();
  assert.equal(t.live.energy().check.summary,"No ribbons because the readings don't balance — check the Electric panel / house sensor");
  assert.equal(document.querySelector('#twin-energy-check [data-energy-role="house"]').dataset.status,'unbalanced');
  assert.equal(t.live.energy().ribbons.filter(r=>r.visible).length,0);
  preferences.mapping=f.mapping;t.live.configureEnergy(preferences);await t.live.refresh();
  assert.equal(document.querySelector('#twin-energy-check [data-energy-role="house"]').dataset.status,'ok');
  assert.deepEqual(t.live.energy().ribbons.filter(r=>r.visible).map(r=>[r.id,r.watts]),[['grid:house',1800]]);
  settings.stop();settings=null;await press(link);assert.equal(link.getAttribute('aria-expanded'),'true');
  assert.equal(legend.querySelector('[data-energy-summary]').textContent,t.live.energy().check.summary);
  t.live.setMode('all');assert.equal(legend.querySelector('a'),null);t.live.setMode('energy');assert.ok(legend.querySelector('a'));
 }finally{delete window.chfOpenSettings;settings?.stop();section.remove();t.cleanup();}
 assert.equal(document.querySelector('.twin-energy-check'),null);
});
let failed=0;for(const [name,f]of checks)try{await f();console.log('  ok '+name);}catch(e){failed++;console.log('  FAIL '+name+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} energy check checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
