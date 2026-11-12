"""Run the energy guesser against HA-style states, without a browser."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {guessEnergy, watts, carHome, mappedEntities, flowReading} = await import(file('static/twin/live/energy_mapping.js'));
const {defaultEntities} = await import(file('static/twin/live/glance.js'));
const checks=[], check=(n,f)=>checks.push([n,f]);
const power=(v=1000, unit='W')=>({state:String(v),attributes:{device_class:'power',unit_of_measurement:unit}});
const level={state:'80',attributes:{device_class:'battery',unit_of_measurement:'%'}};
check('Powerwall names and default signs',()=>{
 const m=guessEnergy({'sensor.powerwall_solar_power':power(),'sensor.powerwall_battery_power':power(),
 'sensor.powerwall_site_power':power(),'sensor.powerwall_load_power':power(),'sensor.powerwall_charge':level});
 assert.equal(m.solar_power,'sensor.powerwall_solar_power'); assert.equal(m.battery_power,'sensor.powerwall_battery_power');
 assert.equal(m.grid_power,'sensor.powerwall_site_power'); assert.equal(m.house_power,'sensor.powerwall_load_power');
 assert.equal(m.battery_level,'sensor.powerwall_charge'); assert.equal(m.battery_positive,'discharge'); assert.equal(m.grid_positive,'import');
});
check('Generic device classes and friendly names',()=>{
 const s={'sensor.a':{...power(),attributes:{...power().attributes,friendly_name:'PV production'}},'sensor.grid':power(),'sensor.load':power(),'sensor.battery':power()};
 const m=guessEnergy(s); assert.equal(m.solar_power,'sensor.a'); assert.equal(m.grid_power,'sensor.grid'); assert.equal(m.house_power,'sensor.load'); assert.equal(m.battery_power,'sensor.battery');
 assert.equal(guessEnergy({'sensor.pv_power':power()}).solar_power,'sensor.pv_power');
});
check('energy counters never masquerade as power',()=>{
 const m=guessEnergy({'sensor.solar_energy':{state:'44',attributes:{device_class:'energy',unit_of_measurement:'kWh'}}});
 assert.equal(m.solar_power,null); assert.equal(watts('sensor.solar_energy',{'sensor.solar_energy':{state:'44',attributes:{device_class:'energy'}}}),null);
});
check('no entities degrades to empty mapping',()=>{const m=guessEnergy(); assert.equal(m.solar_power,null); assert.deepEqual(m.cars,[]);});
check('user mapping, explicit None, cars and signs override guesses',()=>{
 const m=guessEnergy({'sensor.solar':power()}, {solar_power:null,house_power:'sensor.chosen',battery_positive:'charge',grid_positive:'export',cars:[],panels:{visible:false,plane:'roof'}});
 assert.equal(m.solar_power,null); assert.equal(m.house_power,'sensor.chosen'); assert.equal(m.battery_positive,'charge'); assert.equal(m.grid_positive,'export'); assert.deepEqual(m.cars,[]); assert.equal(m.panels.visible,false);
 assert.equal(flowReading(2000,m.battery_positive==='discharge').direction,-1);
});
check('car grouping and fleet bindings share one vehicle',()=>{
 const states={'sensor.tesla_charge_power':power(),'sensor.tesla_battery':level,'device_tracker.tesla_location':{state:'home',attributes:{}}};
 const m=guessEnergy(states,{},[{id:'family',name:'Family car',battery_level:'sensor.tesla_battery',location:'device_tracker.tesla_location'}]);
 assert.equal(m.cars.length,1); assert.equal(m.cars[0].charge_power,'sensor.tesla_charge_power'); assert.equal(m.cars[0].name,'Family car');
 assert.equal(carHome(m.cars[0],states),true); states['device_tracker.tesla_location'].state='away'; assert.equal(carHome(m.cars[0],states),false);
 assert.equal(carHome({location:'missing'},states),false); assert.equal(carHome({},states),true);
});
check('units, signed watts and missing readings',()=>{
 assert.equal(watts('x',{x:power(-1.5,'kW')}),-1500); assert.equal(watts('x',{x:power(2,'MW')}),2000000);
 for(const v of ['unknown','unavailable','',null]) assert.equal(watts('x',{x:{state:v,attributes:{device_class:'power'}}}),null);
});
check('mapped readings feed only automatic glance lists',()=>{
 const mapping={solar_power:'sensor.unusual',cars:[{battery_level:'sensor.ev_soc',location:'device_tracker.ev'}]};
 assert.deepEqual(defaultEntities({},[],mapping),['sensor.unusual','sensor.ev_soc']);
 assert.equal(mappedEntities(mapping).length,3);
});
let failed=0; for(const [n,f] of checks)try{await f(); console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
console.log(`${checks.length-failed}/${checks.length} energy mapping checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
