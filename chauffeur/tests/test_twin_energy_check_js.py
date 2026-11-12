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
 const view={plan:{buildings:[b]}},mapping={solar_power:'sensor.solar_power',battery_power:'sensor.battery_power',grid_power:'sensor.grid_power',house_power:'sensor.house_power',cars:[{id:'ev',name:'Family EV',charge_power:'sensor.ev_power'}]};
 const states=Object.fromEntries(keys.map(k=>['sensor.'+k+'_power',power(k==='solar'?4000:k==='house'?2000:k==='battery'?-1000:k==='grid'?-1000:49)]));
 const layout={markers:keys.slice(1).map((k,i)=>({device_id:k,name:k==='battery'?'Powerwall':k,entity_id:'sensor.'+k+'_power',entities:[],placed:true,location_valid:true,building:'b',level:'L1',at:[i*8,0,3]}))};
 return {view,mapping,states,layout};
}
const assess=f=>energyCheck(f.view,f.layout,f.mapping,f.states);
const entityKey=id=>id==='car:0'?'charge_power':id+'_power';
for(const id of ['solar','battery','grid','house','car:0'])for(const scenario of ['unset','unavailable','unplaced','ok'])check(id+' '+scenario,()=>{
 const f=fixture(),object=id==='car:0'?f.mapping.cars[0]:f.mapping,key=entityKey(id),entity=object[key];
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
 if(scenario==='unavailable')assert.equal(row.state,'unavailable');
 if(scenario==='unplaced')assert.ok(row.location.includes(id==='solar'?'add a solar zone':entity));
 if(scenario==='ok')assert.ok(row.location.includes(id==='solar'?'solar zone on roof roof (source)':'Ground floor'));
});
for(const id of ['battery','grid','house','car:0'])check(id+' placed under another entity',()=>{
 const f=fixture(),entity=(id==='car:0'?f.mapping.cars[0].charge_power:f.mapping[id+'_power']);
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
 assert.equal(s.flows.find(r=>r.id==='car:0').watts,49);assert.equal(s.flows.find(r=>r.id==='car:0').status,'hidden (under 50 W)');
 f.states['sensor.ev_power']=power(50);assert.equal(assess(f).flows.find(r=>r.id==='car:0').status,'shown');
 f.layout.markers=f.layout.markers.filter(m=>m.device_id!=='grid');s=assess(f);
 assert.equal(s.flows.find(r=>r.id==='solar:grid').status,'no ribbon: Meter / grid not placed');
 f.states['sensor.solar_power']=power(0);f.states['sensor.house_power']=power(500);f.states['sensor.battery_power']=power(-1000);f.states['sensor.grid_power']=power(1500);f.states['sensor.ev_power']=power(0);
 s=assess(f);assert.equal(s.summary,'No ribbons because Meter / grid not placed');
 for(const id of ['grid:house','grid:battery'])assert.equal(s.flows.find(r=>r.id===id).status,'no ribbon: Meter / grid not placed');
});
check('summary explains missing power and quiet totals without blaming optional roles',()=>{
 const f=fixture();f.mapping.house_power=null;assert.equal(assess(f).summary,'No ribbons because Electric panel / house power not set');
 f.mapping.house_power='sensor.house_power';for(const r of Object.values(f.states))r.state='0';
 f.mapping.battery_power=null;f.mapping.grid_power=null;
 assert.equal(assess(f).summary,'No ribbons because all allocated flows are under 50 W');
 f.states['sensor.house_power'].state='unavailable';assert.equal(assess(f).summary,'No ribbons because Electric panel / house power unavailable');
});
check('object locations name the wall and removed selections do not fall back',()=>{
 const f=fixture(),b=f.view.plan.buildings[0];b.walls=[{id:'outside-wall',level:'L1',from:[0,0],to:[20,0],thickness:.5}];
 b.anchors=[{id:'meter',kind:'meter',host:{wall:'outside-wall',side:'right',at:4,z:4}}];
 f.mapping.locations={grid:{type:'object',id:'meter',building:'b'}};
 assert.equal(assess(f).roles[2].location,'meter object on wall outside-wall');
 b.anchors=[];const row=assess(f).roles[2];assert.equal(row.status,'unplaced');assert.ok(row.location.includes('add a meter object'));assert.ok(row.location.includes('selected location'));
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
