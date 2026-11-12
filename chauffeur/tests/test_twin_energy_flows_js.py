"""Explicit power-balance tables, source budgets and real pairwise endpoints."""
import sys
from twin_live_node_rig import run

DRIVER=r"""
const {allocateEnergyFlows,energyFlows,energyBalance,watts,guessEnergy}=await import(file('static/twin/live/energy_mapping.js'));
const {energyTopology,flowCurve,worldPoint}=await import(file('static/twin/live/energy_geometry.js'));
const checks=[],check=(name,f)=>checks.push([name,f]);
// Watts. B > 0 discharges; G > 0 imports; H already includes chargers.
const tables=[
 {name:'midday export',totals:{solar:8000,battery:-2000,grid:-3000,home:3000},
  flows:{'solar:house':3000,'solar:battery':2000,'solar:grid':3000}},
 {name:'evening battery to home',totals:{solar:0,battery:4000,grid:0,home:4000},
  flows:{'battery:house':4000}},
 {name:'storm-watch grid to battery',totals:{solar:0,battery:-5000,grid:6200,home:1200},
  flows:{'grid:house':1200,'grid:battery':5000}},
 {name:'battery export to grid',totals:{solar:0,battery:6000,grid:-4000,home:2000},
  flows:{'battery:house':2000,'battery:grid':4000}},
 {name:'grid to home plus solar to home',totals:{solar:1000,battery:0,grid:2500,home:3500},
  flows:{'solar:house':1000,'grid:house':2500}},
 {name:'car charging from the panel',totals:{solar:4000,battery:0,grid:2000,home:6000,chargers:[2000]},
  flows:{'solar:house':4000,'grid:house':2000,'car:0':2000}}
];
for(const table of tables)check(table.name,()=>assert.deepEqual(allocateEnergyFlows(table.totals),table.flows));
check('home flag adds chargers only when the home sensor excludes them',()=>{
 assert.equal(guessEnergy({},{}).home_includes_chargers,true);
 const t={solar:4000,battery:0,grid:2000,home:4000,chargers:[2000]};
 assert.deepEqual(allocateEnergyFlows(t,{home_includes_chargers:false}),tables[5].flows);
 assert.deepEqual(allocateEnergyFlows({...t,home:6000},{home_includes_chargers:true}),tables[5].flows);
 assert.deepEqual(allocateEnergyFlows(t),{'solar:house':4000,'car:0':2000});
});
check('both saved sign conventions normalize before allocation',()=>{
 for(const table of tables){
  const reversed={...table.totals,battery:-table.totals.battery,grid:-table.totals.grid};
  assert.deepEqual(allocateEnergyFlows(reversed,{battery_positive:'charge',grid_positive:'export'}),table.flows);
 }
});
check('solar and discharge priorities split charging and export correctly',()=>{
 const tables=[
  [{solar:3000,battery:-5000,grid:3000,home:1000},{'solar:house':1000,'solar:battery':2000,'grid:battery':3000}],
  [{solar:1000,battery:5000,grid:-2000,home:4000},{'solar:house':1000,'battery:house':3000,'battery:grid':2000}]
 ];
 for(const [totals,flows]of tables)assert.deepEqual(allocateEnergyFlows(totals),flows);
});
check('threshold is applied after allocation without redirecting small flows',()=>{
 assert.deepEqual(allocateEnergyFlows({solar:99,home:49,grid:-50}),{'solar:grid':50});
 assert.deepEqual(allocateEnergyFlows({solar:98,home:49,grid:-49}),{});
 assert.deepEqual(allocateEnergyFlows({solar:-1,battery:NaN,grid:Infinity,home:-10,chargers:[-1,49,50]}),{'car:2':50});
});
check('residual exports follow the specified priority and grid import never exceeds its total',()=>{
 const tables=[
  [{solar:8000,battery:-2000,grid:-500,home:3000},{'solar:house':3000,'solar:battery':2000,'solar:grid':3000}],
  [{solar:0,battery:-5000,grid:2000,home:1200},{'grid:house':1200,'grid:battery':800}],
  [{solar:0,battery:6000,grid:-1000,home:2000},{'battery:house':2000,'battery:grid':4000}]
 ];
 for(const [totals,flows]of tables)assert.deepEqual(allocateEnergyFlows(totals),flows);
});
check('unbalanced import draws only the reported house consumption without inventing a destination',()=>{
 assert.deepEqual(allocateEnergyFlows({solar:0,battery:0,grid:1800,home:0}),{});
 assert.deepEqual(allocateEnergyFlows({solar:0,battery:0,grid:1800,home:500}),{'grid:house':500});
});
check('each table flow has exact source and destination anchors',()=>{
 const a={solar:[11,23,31],battery:[5,17,4],grid:[-12,9,3],house:[20,13,5],cars:[[27,3,2]]};
 const topology=energyTopology(a,{cars:[{charge_power:'sensor.ev'}]});
 for(const table of tables)for(const [id,watts]of Object.entries(allocateEnergyFlows(table.totals))){
  const row=topology.find(r=>r.id===id);assert.ok(row,id);
  const from=id.startsWith('car:')?a.house:a[id.split(':')[0]],to=id.startsWith('car:')?a.cars[0]:a[id.split(':')[1]];
  assert.deepEqual(row.from,from);assert.deepEqual(row.to,to);
  const curve=flowCurve(row.from,row.to,10);assert.ok(curve.getPoint(0).distanceTo(worldPoint(from))<1e-10);assert.ok(curve.getPoint(1).distanceTo(worldPoint(to))<1e-10);
 }
 // Missing battery never reroutes its charging/export to the panel or meter.
 const missing=energyTopology({...a,battery:null},{cars:[{charge_power:'sensor.ev'}]});
 assert.ok(!missing.some(r=>r.id.split(':').includes('battery')));
});
check('live unit conversion, zone fallback, presence and missing readings use the same allocator',()=>{
 const power=(state,unit='W')=>({state:String(state),attributes:{device_class:'power',unit_of_measurement:unit}});
 const mapping={battery_power:'sensor.b',grid_power:'sensor.g',house_power:'sensor.h',cars:[{charge_power:'sensor.ev',location:'device_tracker.ev'}]};
 const states={'sensor.z':power(4,'kW'),'sensor.b':power(0),'sensor.g':power(2000),'sensor.h':power(6000),'sensor.ev':power(2000),'device_tracker.ev':{state:'home'}};
 assert.deepEqual(energyFlows(mapping,states,['sensor.z']),tables[5].flows);
 states['device_tracker.ev'].state='away';assert.deepEqual(energyFlows(mapping,states,['sensor.z']),{'solar:house':4000,'grid:house':2000});
 states['sensor.z'].attributes.unit_of_measurement='kWh';delete states['sensor.g'];assert.deepEqual(energyFlows(mapping,states,['sensor.z']),{});
 states['device_tracker.ev'].state='home';assert.deepEqual(energyFlows(mapping,states,['sensor.z']),{'car:0':2000});
 delete states['sensor.h'];states['sensor.z']=power(4000);assert.deepEqual(energyFlows(mapping,states,['sensor.z']),{'car:0':2000});
});
check('one missing total is worked out from the other three; two missing leave the balance unknown',()=>{
 const power=(state,unit='W')=>({state:String(state),attributes:{device_class:'power',unit_of_measurement:unit}});
 const mapping={solar_power:'sensor.s',battery_power:'sensor.b',grid_power:'sensor.g',house_power:'sensor.h',cars:[]};
 // Night: no sun, the Powerwall idle, the house drawing 1.5 kW from the grid (Powerwall-style kW sensors).
 const states={'sensor.s':power(0,'kW'),'sensor.b':power(0,'kW'),'sensor.g':power(1.5,'kW'),'sensor.h':power(1.5,'kW')};
 assert.deepEqual(energyFlows(mapping,states),{'grid:house':1500});
 for(const key of ['sensor.s','sensor.b','sensor.g','sensor.h']){
  const partial={...states};delete partial[key];
  const balance=energyBalance(mapping,partial);
  assert.equal(balance.known,true,key);assert.equal(Object.keys(balance.derived).length,1,key);
  assert.deepEqual(energyFlows(mapping,partial),{'grid:house':1500},key);
 }
 const two={...states};delete two['sensor.g'];delete two['sensor.h'];
 assert.equal(energyBalance(mapping,two).known,false);assert.deepEqual(energyFlows(mapping,two),{});
 // An energy counter is never read as a flow, even with device_class power.
 assert.equal(watts('sensor.e',{'sensor.e':power(4,'kWh')}),null);
});
let failures=0;for(const [name,f]of checks)try{f();console.log('  ok '+name);}catch(e){failures++;console.log('  FAIL '+name+' '+e.stack);}
assert.deepEqual(escaped,[]);assert.deepEqual(domErrors,[]);console.log(`${checks.length-failures}/${checks.length} energy flow checks passed`);process.exit(failures?1:0);
"""
if __name__=='__main__':sys.exit(run(DRIVER))
