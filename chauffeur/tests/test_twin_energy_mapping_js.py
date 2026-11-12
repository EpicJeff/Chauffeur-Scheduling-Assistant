"""Run the energy guesser against HA-style states, without a browser."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {guessEnergy, watts, carHome, carPower, mappedEntities, flowReading, migrateEnergy, chargingCar, chargingDecision, assignParking} = await import(file('static/twin/live/energy_mapping.js'));
const {mountGlance} = await import(file('static/twin/live/glance.js'));
const checks=[], check=(n,f)=>checks.push([n,f]);
const power=(v=1000, unit='W')=>({state:String(v),attributes:{device_class:'power',unit_of_measurement:unit}});
const level={state:'80',attributes:{device_class:'battery',unit_of_measurement:'%'}};
check('car power uses bindings, including unavailable readings; unknown displays as fuel',()=>{
 for(const binding of ['battery_level','charging','charge_power']){
  assert.equal(carPower({[binding]:'sensor.ev'}),'electric');
  assert.equal(carPower({[binding]:'sensor.ev',fuel_level:'sensor.fuel'}),'hybrid');
 }
 assert.equal(carPower({fuel_level:'sensor.fuel'}),'fuel');
 assert.equal(carPower({}),'fuel');assert.equal(carPower({battery_level:null,fuel_level:null}),'fuel');
});
check('fuel telemetry matches the fleet stem and never becomes battery, even with charge in its name',()=>{
 const fuel={state:'41',attributes:{unit_of_measurement:'%',friendly_name:'GLS charge / fuel level'}};
 for(const fleet of [[{id:'gls',name:'Mercedes GLS',fuel_level:'sensor.gls_fuel_level'}],
                     [{id:'family',name:'Mercedes GLS',location:'device_tracker.gls'}]]){
  const m=guessEnergy({'sensor.gls_fuel_level':fuel,'device_tracker.gls':{state:'home'}},{},fleet);
  assert.equal(m.cars.length,1);assert.equal(m.cars[0].fuel_level,'sensor.gls_fuel_level');
  assert.ok(!m.cars[0].battery_level);assert.equal(carPower(m.cars[0]),'fuel');
  assert.ok(mappedEntities(m,true).includes('sensor.gls_fuel_level'));
 }
 const m=guessEnergy({'sensor.car_gls_fuel_level':fuel});
 assert.equal(m.cars.length,1);assert.equal(m.cars[0].fuel_level,'sensor.car_gls_fuel_level');assert.ok(!m.cars[0].battery_level);
 const saved=guessEnergy({}, {cars:[{id:'gls',name:'GLS',battery_level:null}],chargers:[]},
  [{id:'gls',fuel_level:'sensor.gls_fuel_level',range_entity:'sensor.gls_range',fuel_warn_pct:45,color:'#123456'}]);
 assert.equal(saved.cars[0].fuel_level,'sensor.gls_fuel_level');assert.equal(saved.cars[0].fuel_warn_pct,45);
});
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
check('Tesla gateway friendly names keep four distinct power roles and saved choices',()=>{
 const states=Object.fromEntries(['battery','site','load','solar'].map(role=>['sensor.powerwall_'+role+'_power',
  {...power(),attributes:{...power().attributes,friendly_name:'Home Energy Gateway '+role[0].toUpperCase()+role.slice(1)+' power'}}]));
 const m=guessEnergy(states);
 assert.deepEqual([m.solar_power,m.battery_power,m.grid_power,m.house_power],
  ['sensor.powerwall_solar_power','sensor.powerwall_battery_power','sensor.powerwall_site_power','sensor.powerwall_load_power']);
 assert.equal(new Set([m.solar_power,m.battery_power,m.grid_power,m.house_power]).size,4);
 const saved=guessEnergy(states,{house_power:'sensor.powerwall_battery_power'});
 assert.equal(saved.house_power,'sensor.powerwall_battery_power');assert.equal(saved.battery_power,null);
});
check('specific entity ids beat friendly names and load beats home',()=>{
 const named=name=>({...power(),attributes:{...power().attributes,friendly_name:name}});
 const states={'sensor.a':named('Load power'),'sensor.home_power':power(),'sensor.powerwall_load_power':named('Home Energy Gateway power')};
 assert.equal(guessEnergy(states).house_power,'sensor.powerwall_load_power');
 delete states['sensor.powerwall_load_power'];assert.equal(guessEnergy(states).house_power,'sensor.a');
});
check('home in a device name never turns another power role into the house',()=>{
 for(const kind of ['battery','grid','site','solar','pv','charge','charger','charging','gateway_battery']){
  const row={...power(),attributes:{...power().attributes,friendly_name:'Home Energy Gateway '+kind+' power'}};
  assert.equal(guessEnergy({['sensor.'+kind+'_power']:row}).house_power,null,kind);
  assert.equal(guessEnergy({'sensor.a':row}).house_power,null,kind+' friendly name');
 }
 assert.equal(guessEnergy({'sensor.home_power':power()}).house_power,'sensor.home_power');
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
check('mapped readings remain available to energy without inventing glance tiles',()=>{
 const mapping={solar_power:'sensor.unusual',cars:[{battery_level:'sensor.ev_soc',location:'device_tracker.ev'}]};
 const host=document.createElement('div'),glance=mountGlance(host);
 glance.energy(mapping);assert.equal(glance.bar.hidden,true);assert.equal(glance.bar.children.length,0);glance.stop();
 assert.equal(mappedEntities(mapping).length,3);
 assert.deepEqual(mappedEntities(mapping,true),['sensor.unusual','sensor.ev_soc']);
});

check('legacy read migrates chargers without mutation and preserves own power in the new shape',()=>{
 const old={cars:[{id:'ev',name:'EV',charge_power:'sensor.ev_power',anchor:{type:'device',id:'evse'}}]};
 const copy=structuredClone(old),m=migrateEnergy(old);assert.deepEqual(old,copy);
 assert.deepEqual(m.chargers,[{id:'charger-ev',name:'EV charger',power:'sensor.ev_power',anchor:{type:'device',id:'evse'},car:'ev'}]);
 assert.equal(m.cars[0].charge_power,null);assert.equal(m.cars[0].anchor,null);assert.deepEqual(migrateEnergy(m),m);
 const modern={...old,chargers:[]};assert.deepEqual(migrateEnergy(modern),modern);
 assert.deepEqual(guessEnergy({},old).chargers,m.chargers);
});
check('Tesla fixture separates wall connector from car telemetry including charging state',()=>{
 const states={'sensor.wall_connector_power':power(7000),'sensor.my_ev_charger_power':power(7100),
 'binary_sensor.my_ev_charging':{state:'on',attributes:{}},'sensor.my_ev_battery_level':level,'sensor.powerwall_battery_power':power(1000)};
 const m=guessEnergy(states);assert.equal(m.chargers.length,1);assert.equal(m.chargers[0].power,'sensor.wall_connector_power');
 assert.equal(m.cars.length,1);assert.equal(m.cars[0].charge_power,'sensor.my_ev_charger_power');assert.equal(m.cars[0].charging,'binary_sensor.my_ev_charging');
 assert.ok(mappedEntities(m).includes('sensor.wall_connector_power'));assert.ok(mappedEntities(m).includes('binary_sensor.my_ev_charging'));
 const sensor={...states,'sensor.my_ev_charging_state':{state:'charging',attributes:{}}};delete sensor['binary_sensor.my_ev_charging'];
 assert.equal(guessEnergy(sensor).cars[0].charging,'sensor.my_ev_charging_state');
});
const cars=[{id:'a',name:'A',charging:'binary_sensor.a_charging',charge_power:'sensor.a_power',location:'device_tracker.a'},
 {id:'b',name:'B',charging:'sensor.b_charging_state',charge_power:'sensor.b_power'}];
const charger={id:'evse',power:'sensor.evse',at:[0,0,3]},spots=[{id:'p1',car:'a',at:[6,0,0]},{id:'p2',car:'b',at:[20,0,0]}];
const telemetry=()=>({'sensor.evse':power(7000),'binary_sensor.a_charging':{state:'off'},'sensor.b_charging_state':{state:'idle'},'device_tracker.a':{state:'home'}});
check('fuel and unknown cars are never charging candidates under any matching rule',()=>{
 const petrol={id:'petrol',name:'Mercedes GLS',fuel_level:'sensor.gls_fuel_level'},ev={id:'ev',battery_level:'sensor.ev_battery'};
 const states=telemetry(),parking=[{id:'fuel',car:'petrol',at:[1,0,0]},{id:'electric',car:'ev',at:[20,0,0]}];
 assert.equal(chargingCar(charger,[petrol,ev],states,parking).id,'ev');
 assert.equal(chargingCar(charger,[petrol],states,parking),null);
 assert.equal(chargingCar({...charger,car:'petrol'},[petrol,ev],states,parking),null);
 assert.equal(chargingDecision({...charger,car:'petrol'},[petrol,ev],states,parking).reason,
  'Mercedes GLS has no battery reading; a charger can only charge an electric car');
 assert.equal(chargingCar(charger,[{id:'petrol'}],states,parking),null);
 assert.equal(chargingCar({...charger,car:'petrol'},[{id:'petrol'}],states,parking),null);
 assert.equal(chargingCar(charger,[{...ev,fuel_level:'sensor.hybrid_fuel'}],states,parking).id,'ev');
});
check('dedicated car wins over charging sensors, but an away car is never selected',()=>{
 const states=telemetry();states['sensor.b_charging_state'].state='charging';
 assert.equal(chargingCar({...charger,car:'a'},cars,states,spots).id,'a');states['device_tracker.a'].state='away';
 assert.notEqual(chargingCar({...charger,car:'a'},cars,states,spots)?.id,'a');
});
check('one charging sensor wins, two produce an explained unknown even with nearer spots',()=>{
 const states=telemetry();states['sensor.b_charging_state'].state='charging';assert.equal(chargingCar(charger,cars,states,spots).id,'b');
 states['binary_sensor.a_charging'].state='on';assert.equal(chargingCar(charger,cars,states,spots),null);assert.equal(chargingDecision(charger,cars,states,spots).reason,'both cars report charging');
 states['device_tracker.a'].state='away';assert.equal(chargingCar(charger,cars,states,spots).id,'b');
});
check('own power matching uses 20 percent or 300 watts and refuses ties',()=>{
 const states=telemetry();states['sensor.b_power']=power(5700);assert.equal(chargingCar(charger,cars,states,spots).id,'b');
 states['sensor.a_power']=power(7000);assert.equal(chargingCar(charger,cars,states,spots),null);
 states['sensor.evse']=power(1000);states['sensor.b_power']=power(1299);states['sensor.a_power']=power(0);assert.equal(chargingCar(charger,cars,states,spots).id,'b');
});
check('nearest home spot within 30 feet wins; tied and far spots stay unknown',()=>{
 const states=telemetry();assert.equal(chargingCar(charger,cars,states,spots).id,'a');
 assert.equal(chargingCar(charger,cars,states,[{...spots[0],at:[20,0,0]},spots[1]]),null);
 assert.equal(chargingCar(charger,cars,states,spots.map(s=>({...s,at:[31,0,0]}))),null);
 states['device_tracker.a'].state='away';assert.equal(chargingCar(charger,cars,states,spots).id,'b');
});
check('parking reserves assigned spots before free spots and follows fleet order',()=>{
 const order=guessEnergy({}, {cars:[...cars].reverse(),chargers:[]},cars);assert.deepEqual(order.cars.map(c=>c.id),['a','b']);
 const all=[{id:'free',at:[0,0,0]},{id:'assigned',assigned:'b',at:[10,0,0]},{id:'other',assigned:'away',at:[20,0,0]}];
 const assigned=assignParking(cars,all,telemetry());assert.equal(assigned.find(s=>s.car==='a').id,'free');assert.equal(assigned.find(s=>s.car==='b').id,'assigned');
 const reverse=assignParking([...cars].reverse(),all.slice(0,1),telemetry());assert.equal(reverse[0].car,'b');
 assert.equal(assignParking(cars,[],telemetry()).length,0);
 const states=telemetry();states['device_tracker.a'].state='away';assert.ok(!assignParking(cars,all,states).some(s=>s.car==='a'));
});

check('equipment shelf values reconcile with saved chargers and new objects remain discoverable',()=>{
 const ref={type:'object',building:'b',id:'wallbox'},object={id:'wallbox',kind:'charger',power:'sensor.new',car:'b',name:'Renamed'};
 const plan={buildings:[{id:'b',anchors:[object]}]};
 const saved={cars:[],chargers:[{id:'saved',name:'Old',power:'sensor.old',anchor:ref,car:'a'}]};
 const m=guessEnergy({},saved,[],plan);assert.equal(m.chargers.length,1);assert.equal(m.chargers[0].power,'sensor.new');assert.equal(m.chargers[0].car,'b');assert.equal(m.chargers[0].name,'Renamed');
 assert.equal(guessEnergy({},{chargers:[]},[],plan).chargers.length,1);
 object.power=null;assert.equal(guessEnergy({},{chargers:[]},[],plan).chargers.length,0);
 const bad={'sensor.wall_connector_total':{state:'2',attributes:{device_class:'power',unit_of_measurement:'kWh'}}};assert.equal(guessEnergy(bad).chargers.length,0);
 const legacy=migrateEnergy({cars:[{id:'ev',name:'x'.repeat(100),charge_power:'sensor.ev'}]});assert.equal(legacy.chargers[0].name.length,100);
});
let failed=0; for(const [n,f] of checks)try{await f(); console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
console.log(`${checks.length-failed}/${checks.length} energy mapping checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
