"""Cars, parking and charger links exercised through mounted JS paths."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {mountCars,carTexture}=await import(file('static/twin/live/cars.js'));
const {mountEnergy}=await import(file('static/twin/live/energy.js'));
const {energyCheck}=await import(file('static/twin/live/energy_check.js'));
const checks=[],check=(name,fn)=>checks.push([name,fn]);
globalThis.Path2D=class {constructor(path){this.path=path;}};
const power=v=>({state:String(v),attributes:{device_class:'power',unit_of_measurement:'W'}});
async function fixture(modelLoader){
 const t=await rig({devices:[]}),b=t.view.plan.buildings[0];
 b.walls=[{id:'w',level:'L1',from:[-20,0],to:[20,0],thickness:.5}];
 b.anchors=[{id:'panel',kind:'electric_panel',host:{wall:'w',side:'left',at:5,z:4}},
  {id:'evse',kind:'charger',name:'Garage charger',host:{wall:'w',side:'left',at:20,z:4}},
  {id:'p1',kind:'parking',car:'a',host:{floor:'r',u:.3,v:.5}},
  {id:'p2',kind:'parking',car:'b',host:{floor:'r',u:.7,v:.5}}];
 const mapping={house_power:'sensor.load',grid_power:'sensor.grid',locations:{house:{type:'object',id:'panel',building:'b'}},
  chargers:[{id:'evse',name:'Garage charger',power:'sensor.evse',anchor:{type:'object',id:'evse',building:'b'}}],
  cars:[{id:'a',name:'Red EV',battery_level:'sensor.a_battery',charging:'binary_sensor.a_charging',location:'device_tracker.a'},
  {id:'b',name:'Blue EV',battery_level:'sensor.b_battery',charging:'binary_sensor.b_charging'}]};
 Object.assign(t.states,{'sensor.load':power(7000),'sensor.grid':power(7000),'sensor.evse':power(7000),
  'sensor.a_battery':{state:'78',attributes:{}},'sensor.b_battery':{state:'15',attributes:{}},
  'binary_sensor.a_charging':{state:'on'},'binary_sensor.b_charging':{state:'off'},'device_tracker.a':{state:'home'},
  'sensor.a_range':{state:'210',attributes:{unit_of_measurement:'mi'}}});
 t.view.energySources={mapping,cars:[{id:'a',color:'#cc0000',range_entity:'sensor.a_range',battery_warn_pct:20},{id:'b',color:'#0000cc',battery_warn_pct:20}]};
 await t.live.refresh();
 t.layer=mountCars({view:t.view,live:t.live,modelLoader});t.layer.draw();return t;
}
check('car glyph textures use colour contrast and rings on the shared disc style',()=>{
 for(const color of ['#ffffff','#000000','#cc0000']){
  const texture=carTexture(color,'#9957d2'),log=texture.image.__log;
  assert.ok(log.some(r=>r[0]==='fill'));assert.ok(log.some(r=>r[0]==='stroke'));texture.dispose();
 }
});
check('two cars show fleet colours in every mode, labels, range and a tappable card',async()=>{
 const t=await fixture();try{
  for(const mode of ['all','energy','lights','security','climate','all']){t.live.setMode(mode);t.layer.draw();assert.equal(t.layer.snapshot().filter(r=>r.visible).length,2);}
  const rows=t.layer.snapshot();assert.equal(rows[0].color,'#cc0000');assert.equal(rows[1].color,'#0000cc');
  assert.match(rows[0].label,/78%.*7 kW/);assert.equal(rows[0].charging,true);assert.equal(rows[1].charging,false);
  await press(document.querySelector('[data-car-icon="a"]'));const card=document.querySelector('[data-car-card="a"]');
  assert.ok(!card.hidden);assert.match(card.textContent,/210 mi/);assert.match(card.textContent,/Garage charger/);assert.doesNotMatch(card.textContent,/Not home/);
 }finally{t.layer.stop();t.cleanup();}
});
check('electric, fuel, hybrid and unknown labels and cards follow their configured bindings',async()=>{
 const t=await fixture();try{
  t.view.energySources.mapping.chargers=[];
  const car=t.view.energySources.mapping.cars[0];car.name='Mercedes GLS';car.charging=null;car.battery_level=null;
  car.fuel_level='sensor.gls_fuel_level';
  t.states[car.fuel_level]={state:'41',attributes:{unit_of_measurement:'%'}};
  await t.live.refresh();t.layer.update();assert.equal(t.layer.snapshot()[0].label,'Mercedes GLS · ⛽ 41%');
  await press(document.querySelector('[data-car-icon="a"]'));let card=document.querySelector('[data-car-card="a"]');
  assert.match(card.textContent,/Fuel: 41%/);assert.match(card.textContent,/Range: 210 mi/);
  assert.doesNotMatch(card.textContent,/Battery:|[Cc]harging|Charger:|kW/);
  car.battery_level='sensor.a_battery';t.layer.update();
  assert.equal(t.layer.snapshot()[0].label,'Mercedes GLS · 🔋 78% · ⛽ 41%');
  assert.match(card.textContent,/Battery: 78%/);assert.match(card.textContent,/Fuel: 41%/);assert.match(card.textContent,/Not charging/);
  t.states[car.fuel_level].state='unavailable';t.states[car.battery_level].state='unknown';await t.live.refresh();t.layer.draw();
  assert.equal(t.layer.snapshot()[0].label,'Mercedes GLS · 🔋 — · ⛽ —');
  assert.match(card.textContent,/Battery: —/);assert.match(card.textContent,/Fuel: —/);
  car.fuel_level=null;car.name='Kia EV9';t.states[car.battery_level].state='99';await t.live.refresh();t.layer.update();
  assert.equal(t.layer.snapshot()[0].label,'Kia EV9 · 🔋 99%');assert.doesNotMatch(card.textContent,/Fuel:/);
  car.battery_level=null;t.layer.update();assert.equal(t.layer.snapshot()[0].label,'Kia EV9 · ⛽ —');
  assert.match(card.textContent,/Fuel: —/);assert.doesNotMatch(card.textContent,/Battery:|[Cc]harging|Charger:/);
 }finally{t.layer.stop();t.cleanup();}
});
check('low fuel uses the household attention threshold, charging wins, and cached textures reuse materials',async()=>{
 const {twinAttention}=await import(file('static/twin/palette.js'));
 const t=await fixture();try{
  const car=t.view.energySources.mapping.cars[0],fleet=t.view.energySources.cars[0];
  car.fuel_level='sensor.gls_fuel_level';car.battery_level=null;car.charging=null;
  fleet.fuel_warn_pct=45;t.states[car.fuel_level]={state:'41',attributes:{unit_of_measurement:'%'}};
  await t.live.refresh();t.layer.update();let sprite;t.view.scene.traverse(o=>{if(o.userData.twinCar==='a')sprite=o;});
  const material=sprite.material,amber=material.map;
  assert.ok(amber.image.__log.some(r=>r[0]==='stroke' && r[1].strokeStyle===twinAttention));
  assert.equal(t.layer.snapshot()[0].charging,false);
  await press(document.querySelector('[data-car-icon="a"]'));
  assert.doesNotMatch(document.querySelector('[data-car-card="a"]').textContent,/[Cc]harging|Charger:/);
  t.states[car.fuel_level].state='45';await t.live.refresh();t.layer.draw();const normal=material.map;assert.notEqual(normal,amber);
  t.states[car.fuel_level].state='41';await t.live.refresh();t.layer.draw();assert.equal(material.map,amber);
  car.battery_level='sensor.a_battery';car.charging='binary_sensor.a_charging';t.layer.update();
  assert.ok(material.map.image.__log.some(r=>r[0]==='stroke' && r[1].strokeStyle==='#9957d2'));
  assert.equal(sprite.material,material);assert.equal(t.layer.snapshot()[0].label,'Red EV · 🔋 78% · ⛽ 41% · ⚡ 7 kW');
 }finally{t.layer.stop();t.cleanup();}
});
check('a nearer fuel car never receives the charger cable when the EV is not reporting charging',async()=>{
 const t=await fixture();let effect;try{
  const car=t.view.energySources.mapping.cars[0];car.battery_level=null;car.charging=null;car.fuel_level='sensor.gls_fuel_level';
  t.states['binary_sensor.b_charging'].state='off';
  effect=mountEnergy({view:t.view,live:t.live});effect.update('energy');
  assert.ok(effect.snapshot().ribbons.filter(r=>r.visible && r.link).every(r=>r.id==='link:0:b:p2'));
  t.view.energySources.mapping.chargers[0].car='a';effect.update('energy');
  assert.ok(!effect.snapshot().ribbons.some(r=>r.visible && r.link));
 }finally{effect?.stop();t.layer.stop();t.cleanup();}
});
check('a saved car inherits Drive fuel and accepts its first reading on the live stream',async()=>{
 const previous=globalThis.EventSource,sources=[];
 globalThis.EventSource=class{constructor(){sources.push(this);}close(){this.closed=true;}};
 const t=await fixture();try{
  const car=t.view.energySources.mapping.cars[0];car.battery_level=null;car.charging=null;
  t.view.energySources.cars[0].fuel_level='sensor.unusual_remaining';
  t.view.energySources.cars[0].range_entity='sensor.unusual_distance';
  t.live.configureEnergy(t.view.energySources);t.layer.update();assert.match(t.layer.snapshot()[0].label,/⛽ —/);
  const stream=sources.at(-1);assert.ok(stream && !stream.closed);
  for(const [entity_id,state,unit]of [['sensor.unusual_remaining','41','%'],['sensor.unusual_distance','180','mi']])
   stream.onmessage({data:JSON.stringify({entity_id,state:{state,attributes:{unit_of_measurement:unit}}})});
  await wait(60);t.layer.draw();assert.match(t.layer.snapshot()[0].label,/⛽ 41%/);
  await press(document.querySelector('[data-car-icon="a"]'));
  assert.match(document.querySelector('[data-car-card="a"]').textContent,/Range: 180 mi/);
 }finally{t.layer.stop();t.cleanup();if(previous===undefined)delete globalThis.EventSource;else globalThis.EventSource=previous;}
});
check('settings show read-only fuel from Drive setup and only chargeable cars offer charging pickers',async()=>{
 const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
 const t=await fixture(),fields=document.createElement('div'),save=document.createElement('button');fields.id='twin-energy-fields';save.id='twin-energy-save';document.body.append(fields,save);
 const mapping=t.view.energySources.mapping;mapping.cars[0]={id:'a',name:'Mercedes GLS',fuel_level:'sensor.gls_fuel_level'};
 mapping.cars.push({id:'hybrid',name:'Hybrid',fuel_level:'sensor.hybrid_fuel',battery_level:'sensor.hybrid_battery'});
 let stored;
 const settings=mountEnergySettings(t.view,{api:async(path,init)=>{
  if(init)stored=JSON.parse(init.body);
  return {ok:true,json:async()=>({mapping,cars:t.view.energySources.cars,can_edit:true})};
 }});
 try{
  await settings.reload();
  for(const [name,fuel,chargeable]of [['Mercedes GLS','sensor.gls_fuel_level',false],['Blue EV','—',true],['Hybrid','sensor.hybrid_fuel',true]]){
   const group=fields.querySelectorAll('fieldset').find(g=>g.querySelector('legend')?.textContent===name);assert.ok(group);
   assert.ok(group.textContent.includes('Fuel entity: '+fuel));assert.ok(group.textContent.includes('Drive setup'));
   for(const title of ['Charging state','Charge power'])assert.equal(group.querySelectorAll('label').some(l=>l.textContent.startsWith(title)),chargeable);
   assert.ok(!group.querySelectorAll('label').some(l=>l.textContent.startsWith('Fuel')));
  }
  const group=fields.querySelectorAll('fieldset').find(g=>g.querySelector('legend')?.textContent==='Mercedes GLS');
  const input=group.querySelector('input');input.value='GLS';input.dispatchEvent(new Event('input'));
  const battery=group.querySelectorAll('label').find(l=>l.textContent.startsWith('Battery level')).querySelector('select');
  battery.value='sensor.a_battery';battery.dispatchEvent(new Event('change'));
  let refreshed=fields.querySelectorAll('fieldset').find(g=>g.querySelector('legend')?.textContent==='GLS');
  assert.ok(refreshed.querySelectorAll('label').some(l=>l.textContent.startsWith('Charging state')));
  const clear=refreshed.querySelectorAll('label').find(l=>l.textContent.startsWith('Battery level')).querySelector('select');
  clear.value='';clear.dispatchEvent(new Event('change'));
  refreshed=fields.querySelectorAll('fieldset').find(g=>g.querySelector('legend')?.textContent==='GLS');
  assert.ok(!refreshed.querySelectorAll('label').some(l=>l.textContent.startsWith('Charging state')));
  await press(save);await wait(30);assert.equal(stored.cars.find(c=>c.id==='a').fuel_level,'sensor.gls_fuel_level');
 }finally{settings.stop();fields.remove();save.remove();t.layer.stop();t.cleanup();}
});
check('state pushes hide away and stale cars, preserve sprites/materials and reuse textures',async()=>{
 const t=await fixture();try{
  const objects=[];t.view.scene.traverse(o=>{if(o.userData.twinCar)objects.push([o,o.material]);});
  const a=objects[0][0],chargingTexture=a.material.map;
  t.states['binary_sensor.a_charging'].state='off';t.states['sensor.evse'].state='0';await t.live.refresh();t.layer.draw();const restingTexture=a.material.map;
  assert.notEqual(restingTexture,chargingTexture);
  t.states['binary_sensor.a_charging'].state='on';t.states['sensor.evse'].state='7000';await t.live.refresh();t.layer.draw();assert.equal(a.material.map,chargingTexture);
  for(const [o,m]of objects){assert.equal(o.material,m);assert.ok(o.parent);}
  t.states['device_tracker.a'].state='away';await t.live.refresh();t.layer.draw();assert.equal(a.visible,false);
  const staleLayer=mountCars({view:t.view,live:{peek:()=>t.states,layout:()=>t.layout,stale:()=>true}});staleLayer.draw();assert.ok(staleLayer.snapshot().every(r=>!r.visible));staleLayer.stop();
 }finally{t.layer.stop();t.cleanup();}
});
check('no HA keeps cars without trackers home with unknown battery; no space hides extras',async()=>{
 const t=await fixture();try{
  t.layer.stop();t.view.energySources.mapping.cars[0].location=null;
  t.view.plan.buildings[0].anchors=t.view.plan.buildings[0].anchors.filter(p=>p.id!=='p2');
  const offline=mountCars({view:t.view,live:()=>null});offline.draw();const rows=offline.snapshot();
  assert.equal(rows[0].visible,true);assert.match(rows[0].label,/—/);assert.equal(rows[1].visible,false);offline.stop();
 }finally{t.cleanup();}
});
check('panel ribbon and flat pulse link select only the charging car without rebuilding on a push',async()=>{
 const t=await fixture();let effect;try{
  effect=mountEnergy({view:t.view,live:t.live});effect.update('energy');effect.draw('energy');
  let rows=effect.snapshot().ribbons,shown=rows.filter(r=>r.visible);
  assert.ok(shown.some(r=>r.id==='charger:0'));assert.deepEqual(shown.filter(r=>r.link).map(r=>r.id),['link:0:b:p1']);
  const link=shown.find(r=>r.link);assert.ok(Math.max(...link.path.map(p=>p[1]))-Math.min(...link.path.map(p=>p[1]))<.001);
  assert.ok(Math.abs(link.width-.25*.3048)<1e-8);
  const objects=[];t.view.scene.traverse(o=>{if(o.userData.energyRibbon)objects.push([o,o.geometry,o.material]);});
  t.states['binary_sensor.a_charging'].state='off';t.states['binary_sensor.b_charging'].state='on';await t.live.refresh();effect.update('energy');
  shown=effect.snapshot().ribbons.filter(r=>r.visible);assert.deepEqual(shown.filter(r=>r.link).map(r=>r.id),['link:0:b:p2']);
  for(const [o,g,m]of objects){assert.equal(o.geometry,g);assert.equal(o.material,m);assert.ok(o.parent);}
  t.view.plan.buildings[0].anchors=t.view.plan.buildings[0].anchors.filter(p=>p.id!=='panel');effect.update('energy');
  shown=effect.snapshot().ribbons.filter(r=>r.visible);assert.ok(!shown.some(r=>r.id==='charger:0'));assert.deepEqual(shown.filter(r=>r.link).map(r=>r.id),['link:0:b:p2']);
  t.states['sensor.evse'].state='49';await t.live.refresh();effect.update('energy');assert.ok(!effect.snapshot().ribbons.some(r=>r.visible && (r.link || r.id==='charger:0')));
 }finally{effect?.stop();t.layer.stop();t.cleanup();}
});
check('Energy check names chargers, parking and ambiguity in words; missing spots are actionable',async()=>{
 const t=await fixture();try{
  t.states['binary_sensor.b_charging'].state='on';let report=energyCheck(t.view,t.layout,t.view.energySources.mapping,t.states);
  assert.match(report.roles.find(r=>r.id==='charger:0').state,/both cars report charging/);
  assert.match(report.roles.find(r=>r.id==='car:a').location,/Parking spot/);
  t.view.plan.buildings[0].anchors=t.view.plan.buildings[0].anchors.filter(p=>p.kind!=='parking');
  report=energyCheck(t.view,t.layout,t.view.energySources.mapping,t.states);assert.equal(report.roles.find(r=>r.id==='car:a').location,'Place a parking spot for Red EV');
 }finally{t.layer.stop();t.cleanup();}
});

check('drawer edits the object-backed charger and removal clears its binding without resurrection',async()=>{
 const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
 const t=await fixture(),fields=document.createElement('div'),save=document.createElement('button');fields.id='twin-energy-fields';save.id='twin-energy-save';document.body.append(fields,save);
 let stored=structuredClone(t.view.energySources.mapping);const operations=[];
 const settings=mountEnergySettings(t.view,{api:async(path,init)=>{
  if(path==='api/house/editor/op'){operations.push(JSON.parse(init.body).op);return {ok:true,json:async()=>({})};}
  if(init)stored=JSON.parse(init.body);
  return {ok:true,json:async()=>({mapping:structuredClone(stored),cars:t.view.energySources.cars,can_edit:true})};
 }});
 try{
  await settings.reload();
  const group=fields.querySelectorAll('fieldset').find(g=>g.querySelector('legend')?.textContent==='Garage charger');assert.ok(group);
  const car=group.querySelectorAll('label').find(l=>l.textContent.startsWith('Dedicated car')).querySelector('select');car.value='b';car.dispatchEvent(new Event('change'));
  await press(save);await wait(30);assert.ok(operations.some(o=>o.field==='car' && o.value==='b' && o.id==='evse'));
  assert.equal(t.view.plan.buildings[0].anchors.find(p=>p.id==='evse').car,'b');
  const remove=fields.querySelectorAll('button').find(b=>b.textContent==='Remove Garage charger');await press(remove);
  assert.ok(!fields.querySelectorAll('fieldset').some(g=>g.querySelector('legend')?.textContent==='Garage charger'));
  await press(save);await wait(30);assert.deepEqual(stored.chargers,[]);assert.ok(operations.some(o=>o.field==='power' && o.value===null));
  t.layer.update();assert.equal(t.view.energySources.mapping.chargers.length,0);
 }finally{settings.stop();fields.remove();save.remove();t.layer.stop();t.cleanup();}
});

check('two modelled cars share GPU resources, keep transforms, align, tap and hide away',async()=>{
 const geometry=new THREE.BoxGeometry(5,1.5,2),material=new THREE.MeshStandardMaterial(),source=new THREE.Group();
 const mesh=new THREE.Mesh(geometry,material);mesh.position.y=.75;source.add(mesh);let loads=0;
 const t=await fixture(async()=>{loads++;return source;});try{
  t.view.tier='high';for(const car of t.view.energySources.cars)car.twin_model='import-shared';
  const spots=t.view.plan.buildings[0].anchors.filter(a=>a.kind==='parking');spots[0].rotation=30;spots[1].rotation=90;
  t.layer.update();await wait(20);t.layer.draw();assert.equal(loads,1);
  const models=[];t.view.scene.traverse(o=>{if(o.userData.carModel && o.parent?.userData.twinCars)models.push(o);});
  assert.equal(models.length,2);assert.notEqual(models[0].position,models[1].position);assert.ok(models[0].position.distanceTo(models[1].position)>1);
  let a,b;models[0].traverse(o=>{if(o.isMesh)a=o;});models[1].traverse(o=>{if(o.isMesh)b=o;});
  assert.equal(a.geometry,b.geometry);assert.equal(a.material,b.material);assert.equal(a.geometry,geometry);assert.equal(a.material,material);
  assert.ok(Math.abs(models[0].rotation.y-(30*Math.PI/180+Math.PI/2))<1e-9);
  const rows=t.layer.snapshot();assert.ok(rows.every(r=>r.model && r.modelVisible));
  assert.ok(rows[0].at[1]>models[0].position.y+1.5,'status floats above real roof');
  await press(document.querySelector('[data-car-icon="a"]'));assert.ok(!document.querySelector('[data-car-card="a"]').hidden);
  await press(document.querySelector('[data-car-card="a"] button'));
  t.view.scene.updateMatrixWorld(true);const point=models[0].position.clone();point.y+=.8;point.z+=.4;point.project(t.camera);
  await t.tapAt([(point.x+1)*700,(1-point.y)*500]);assert.ok(!document.querySelector('[data-car-card="a"]').hidden,'mesh opens same card');
  spots[0].width=18;spots[0].depth=9;t.layer.update();
  assert.ok(Math.abs(models[0].rotation.y-30*Math.PI/180)<1e-9,'resizing a bay realigns the model long axis');
  t.states['device_tracker.a'].state='away';await t.live.refresh();t.layer.update();
  assert.equal(t.layer.snapshot()[0].modelVisible,false);assert.equal(t.layer.snapshot()[0].visible,false);
  t.states['device_tracker.a'].state='home';await t.live.refresh();t.layer.update();assert.equal(t.layer.snapshot()[0].modelVisible,true);assert.equal(loads,1);
 }finally{t.layer.stop();t.cleanup();geometry.dispose();material.dispose();}
});
check('a failed car model keeps its original tappable icon',async()=>{
 const t=await fixture(async()=>{throw new Error('offline');});try{
  t.view.energySources.cars[0].twin_model='import-missing';t.layer.update();await wait(20);t.layer.draw();
  assert.equal(t.layer.snapshot()[0].model,false);assert.equal(t.layer.snapshot()[0].visible,true);
  await press(document.querySelector('[data-car-icon="a"]'));assert.ok(!document.querySelector('[data-car-card="a"]').hidden);
 }finally{t.layer.stop();t.cleanup();}
});
check('a delayed model replaces its icon-only fallback when its load eventually completes',async()=>{
 let late;const source=new THREE.Mesh(new THREE.BoxGeometry(2,1,4),new THREE.MeshStandardMaterial());source.position.y=.5;
 const t=await fixture(async(id,kit,onLate)=>{late=onLate;return null;});try{
  t.view.energySources.cars[0].twin_model='import-delayed';t.layer.update();await wait(20);
  assert.equal(t.layer.snapshot()[0].model,false);late(source);await wait(20);t.layer.draw();
  assert.equal(t.layer.snapshot()[0].modelVisible,true);assert.equal(t.layer.snapshot()[0].visible,true);
 }finally{t.layer.stop();t.cleanup();source.geometry.dispose();source.material.dispose();}
});
check('outdoor parking stays on lot ground despite a raised, rotated building',async()=>{
 const {parkingObjects}=await import(file('static/twin/live/energy_geometry.js'));
 const view={plan:{buildings:[{id:'garage',base:3,position:[20,40],rotation:90,levels:[],walls:[],anchors:[{id:'yard',kind:'parking',host:{ground:true,at:[10,5]}}]}]}};
 const spot=parkingObjects(view)[0];assert.ok(Math.abs(spot.at[0]-15)<1e-9);assert.ok(Math.abs(spot.at[1]-50)<1e-9);assert.ok(Math.abs(spot.at[2]-.08)<1e-9);
});
let failed=0;for(const [name,fn]of checks)try{await fn();console.log('  ok '+name);}catch(e){failed++;console.log('  FAIL '+name+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);console.log(`${checks.length-failed}/${checks.length} car checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.exit(run(DRIVER))
