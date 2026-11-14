"""Mounted energy mode, geometry, warm-up and drawer paths under node."""
import json
from pathlib import Path
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {flowReading} = await import(file('static/twin/live/energy_mapping.js'));
const {energyAnchors,energyTopology,energyPlacementLegend,roofPoints,flowCurve,flowRoute,flowApex,flowFans,lotPoint,worldPoint} = await import(file('static/twin/live/energy_geometry.js'));
const energyModule=await import(file('static/twin/live/energy.js'));
const {flowLabelPositions,mountEnergy,FLOW_COLORS,CONDUIT_COLOR,energyPlace}=energyModule;
const {solarPlanes,solarZones,solarLayout,solarPoint,solarCovered,solarRect}=await import(file('static/twin/twin_solar.js'));
const {mountModes} = await import(file('static/twin/live/modes.js'));
const checks=[], check=(n,f)=>checks.push([n,f]);
const d=(id,entity_id,state,attributes={},kind='sensor')=>({device_id:id,name:id,entity_id,state:String(state),attributes,kind});
const power={device_class:'power',unit_of_measurement:'W'};
async function settleConduits(snapshot) {
 for(let i=0;i<250&&snapshot().conduitPending;i++)await wait(4);
 assert.equal(snapshot().conduitPending,false,'asynchronous conduits settle');
}

const flatRoof=()=>({id:'roof',kind:'flat',rect:[-40,-10,40,20],pitch:0,plate:10,overhang:0,level:'L1'});
async function energyRig(args){
 const devices=[...args.devices];if(!devices.some(d=>d.entity_id==='sensor.house_power'))devices.push(d('panel','sensor.house_power',500,power));
 const t=await rig({...args,devices}),b=t.view.plan.buildings[0];b.walls=[];b.anchors=[];
 b.roof={sections:[flatRoof()]};b.solar_zones=[{id:'z',roof:'roof',plane:[0,0,10],rect:[-30,-5,-10,5]}];
 t.view.plan={...t.view.plan};await t.live.refresh();return t;
}
async function conduitRig(devices = [d('solar','sensor.solar_power',1000,power)]) {
 const t=await energyRig({devices}),b=t.view.plan.buildings[0];
 b.roof={sections:[{...flatRoof(),rect:[-40,-10,0,20]}, {...flatRoof(),id:'remote',rect:[0,-10,40,20]}]};
 b.solar_zones.push({id:'satellite',roof:'remote',plane:[0,0,10],rect:[10,-5,30,5]});
 t.view.plan.solar_source_roof='roof';t.view.plan.solar_source_building=b.id;
 const material=new THREE.MeshStandardMaterial({name:'solar_panel',color:'#285888',emissive:'#123456',emissiveIntensity:.07});
 t.panel=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),material);t.view.scene.add(t.panel);
 await t.live.refresh();await settleConduits(()=>t.live.energy());return t;
}
check('conduit mode visibility, threshold, idle dimming, forward pulse and retained programs',async()=>{
 const t=await conduitRig();try{
  let mesh,halo,metal;t.view.scene.traverse(o=>{if(o.userData.solarConduit)mesh=o;if(o.userData.solarConduitHalo)halo=o;if(o.userData.solarConduitMetal)metal=o;});
  assert.ok(mesh&&halo&&metal);assert.equal(mesh.geometry,halo.geometry);assert.equal(metal.geometry,mesh.geometry,'the metal tube shares the geometry');
  assert.equal(mesh.material.depthTest,true);
  assert.equal(CONDUIT_COLOR,'#4df0ff');assert.equal(mesh.material.uniforms.color.value.getHex(),new THREE.Color(CONDUIT_COLOR).getHex(),'conduit is electric blue');
  assert.ok(Math.abs(mesh.material.uniforms.radius.value-1.5/12*FT)<1e-9);
  const original=[mesh.geometry,mesh.material,mesh.material.customProgramCacheKey(),mesh.material.version];
  for(const mode of ['energy','all','lights','climate','security','energy']){
   t.live.setMode(mode);const shown=['energy','all'].includes(mode);assert.equal(mesh.visible||metal.visible,shown);assert.equal(mesh.visible&&metal.visible,false);
  }
  for(const watts of [0,49,50,5000]){
   t.states['sensor.solar_power'].state=String(watts);await t.live.refresh();t.live.draw();
   const u=mesh.material.uniforms;assert.equal(u.pulseGain.value,watts>=50?1:0);assert.equal(u.brightness.value,watts>=50?1:.15);
   // User, 2026-11-13: at night the conduits are plain metal, not a teal glow.
   assert.equal(mesh.visible,watts>=50,`${watts} W: the glowing tube`);assert.equal(halo.visible,watts>=50,`${watts} W: the halo`);
   assert.equal(metal.visible,watts<50,`${watts} W: the metal tube`);
   assert.equal(metal.material.name,'conduit_metal');assert.ok(metal.material.isMeshStandardMaterial&&metal.material.metalness>=.5);
   const phase=u.phase.value;await wait(20);t.live.draw();
   if(watts>=50)assert.ok(u.phase.value>phase,'positive phase moves along increasing UV toward the source');else assert.equal(u.phase.value,0);
   assert.equal(u.phase.value,halo.material.uniforms.phase.value);
  }
  assert.deepEqual([mesh.geometry,mesh.material,mesh.material.customProgramCacheKey(),mesh.material.version],original);
  const metalMaterial=metal.material;
  for(const watts of [0,5000,0]){t.states['sensor.solar_power'].state=String(watts);await t.live.refresh();t.live.draw();}
  assert.equal(metal.material,metalMaterial,'switching back and forth never makes a new material');
  // Stale data is not producing.
  t.states['sensor.solar_power'].state='5000';await t.live.refresh();t.live.draw();assert.equal(mesh.visible,true);

  const route=t.live.energy().conduits[0],position=mesh.geometry.attributes.position;
  for(let ring=0;ring<route.points.length;ring++){
   const centre=new THREE.Vector3();for(let side=0;side<8;side++)centre.add(new THREE.Vector3().fromBufferAttribute(position,ring*4*9+side));
   centre.multiplyScalar(1/8);assert.ok(centre.distanceTo(worldPoint(route.points[ring]))<1e-5,'every bend has a tube ring');
  }
  // Ridge routing: the conduit ends on the main solar zone (a flat roof: its centre), lifted off the roof.
  const tail=route.points.at(-1);assert.ok(Math.abs(tail[0]+20)<1e-6&&Math.abs(tail[1])<1e-6&&Math.abs(tail[2]-10-2.5/12)<1e-6,JSON.stringify(tail));
 }finally{t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('zone power overrides total, invalid or missing readings fall back, and stale data idles',async()=>{
 const t=await conduitRig([d('solar','sensor.solar_power',4000,power),d('zone','sensor.zone_power',.049,{...power,unit_of_measurement:'kW'})]);let effect;
 try{
  t.live.stop();t.view.plan.buildings[0].solar_zones[1].entity='sensor.zone_power';let stale=false;
  effect=mountEnergy({view:t.view,live:{layout:()=>t.layout,peek:()=>t.states,stale:()=>stale}});effect.update('energy');await effect.ready();
  const reading=()=>effect.snapshot().conduits[0];assert.equal(reading().watts,49);
  let mesh;t.view.scene.traverse(o=>{if(o.userData.solarConduit)mesh=o;});assert.equal(mesh.material.uniforms.pulseGain.value,0);
  t.states['sensor.zone_power'].state='.05';effect.update('energy');assert.equal(reading().watts,50);assert.equal(mesh.material.uniforms.pulseGain.value,1);
  t.states['sensor.zone_power'].state='0';effect.update('energy');assert.equal(reading().watts,0);assert.equal(mesh.material.uniforms.pulseGain.value,0);
  t.states['sensor.zone_power'].state='unavailable';effect.update('energy');assert.equal(reading().watts,4000);
  delete t.states['sensor.zone_power'];effect.update('energy');assert.equal(reading().watts,4000);
  // Stale data is not producing: the conduit is plain metal (user, 2026-11-13).
  let metal;t.view.scene.traverse(o=>{if(o.userData.solarConduitMetal)metal=o;});
  stale=true;effect.update('all');assert.equal(reading().watts,0);assert.equal(mesh.visible,false);assert.equal(metal.visible,true);assert.equal(mesh.material.uniforms.brightness.value,.15);
 }finally{effect?.stop();t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('panels keep their colour; a cyan wave scales with generation and never changes the program again',async()=>{
 const t=await conduitRig();try{
  t.live.setMode('security');const m=t.panel.material,original={color:m.emissive.clone(),intensity:m.emissiveIntensity};
  t.live.setMode('energy');const wave=energyModule.solarWaveOf(m);assert.ok(wave,'wave installed on the panel material');
  // A cloned panel material (the bake copies materials; clone() deep-copies userData as plain
  // data) gets its own working wave and never throws in draw (user, 2026-11-13).
  const copy=m.clone();assert.equal(copy.userData.solarWave,undefined,'the wave is not in userData');
  const copyMesh=new THREE.Mesh(new THREE.BoxGeometry(1,1,1),copy);t.view.scene.add(copyMesh);t.live.refresh&&await t.live.refresh();t.live.setMode('energy');
  t.view.render();const own=energyModule.solarWaveOf(copy);assert.ok(own&&own!==wave&&typeof own.waveDir.value.set==='function','the copy has its own wave');
  copyMesh.removeFromParent();copyMesh.geometry.dispose();
  const key=m.customProgramCacheKey(),version=m.version;assert.ok(key.endsWith('|solarWave'));
  const values=[];for(const watts of [0,1000,2000,100000]){
   t.states['sensor.solar_power'].state=String(watts);await t.live.refresh();t.live.setMode('energy');values.push(wave.waveStrength.value);
   assert.equal(m.emissive.getHex(),original.color.getHex(),'no tint');assert.equal(m.emissiveIntensity,original.intensity);
  }
  assert.equal(values[0],0);assert.ok(values[1]>0&&values[2]>values[1]&&values[3]<=1,JSON.stringify(values));
  t.live.setMode('all');assert.equal(wave.waveStrength.value,values[3]);
  for(const mode of ['lights','climate','security']){t.live.setMode(mode);assert.equal(wave.waveStrength.value,0,mode+': no wave');}
  t.live.setMode('energy');assert.ok(wave.waveStrength.value>0);const realNow=performance.now.bind(performance);let clock=0;performance.now=()=>clock;
  try{
   const cycle=energyModule.PULSE_SECONDS*1000,heads=[];
   for(const f of [.02,.25,.5,.75,.98]){clock=cycle*7+f*cycle;t.view.render();heads.push(wave.waveHead.value);}
   for(let i=1;i<heads.length;i++)assert.ok(heads[i]>heads[i-1],'one front moves forward through the cycle '+JSON.stringify(heads));
   clock=cycle*8+.02*cycle;t.view.render();assert.ok(Math.abs(wave.waveHead.value-heads[0])<1e-9,'the next pulse fires from the start');
   assert.ok(wave.waveWidth.value>0&&Math.abs(wave.waveDir.value.length()-1)<1e-9);
  }finally{performance.now=realNow;}
  t.live.stop();assert.equal(wave.waveStrength.value,0,'stop ends the wave');
  assert.equal(m.emissive.getHex(),original.color.getHex());assert.equal(m.emissiveIntensity,original.intensity);
  assert.equal(m.customProgramCacheKey(),key);assert.equal(m.version,version,'power and mode changes never recompile');
  const shader={uniforms:{},vertexShader:'#include <common>\n#include <begin_vertex>',fragmentShader:'#include <common>\n#include <emissivemap_fragment>'};
  m.onBeforeCompile(shader,null);assert.ok(shader.uniforms.waveStrength===wave.waveStrength&&shader.fragmentShader.includes('totalEmissiveRadiance += waveColor'));
  // One pulse at a time, crossing all panels in under a second, then the next fires.
  assert.ok(energyModule.PULSE_SECONDS<=1);assert.ok(shader.fragmentShader.includes('waveHead - dot(vSolarWave.xz, waveDir)'));

 }finally{t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('visualizations hide with the geometry they are tied to: conduits with their roof, ribbons when both ends hide',async()=>{
 const t=await conduitRig();let effect;try{
  t.live.stop();effect=mountEnergy({view:t.view,live:{layout:()=>t.layout,peek:()=>t.states,stale:()=>false}});
  effect.update('energy');await effect.ready();effect.update('energy');
  const hidden={roofs:new Set(),levels:new Set()};t.view.roofShown=id=>!hidden.roofs.has(id);t.view.levelShown=key=>!hidden.levels.has(key);
  const snap=()=>{effect.draw('energy');return effect.snapshot();};
  const before=snap(),solar=before.ribbons.filter(r=>r.id.startsWith('solar:')&&r.visible);
  assert.ok(before.conduits.length&&before.conduits.every(c=>c.visible),'conduits shown with the roof');assert.ok(solar.length,'a solar ribbon to check');
  const b=t.view.plan.buildings[0];hidden.roofs.add(b.id);
  const roofless=snap();assert.ok(roofless.conduits.every(c=>!c.visible),'conduits go with the panels');
  for(const r of solar)assert.equal(roofless.ribbons.find(x=>x.id===r.id).visible,true,'a solar ribbon stays while its other end shows: '+r.id);
  for(const l of b.levels)hidden.levels.add(b.id+':'+l.id);
  const none=snap();assert.ok(none.ribbons.filter(r=>r.id.startsWith('solar:')).every(r=>!r.visible),'both ends hidden: the ribbon goes');
  hidden.roofs.clear();hidden.levels.clear();const back=snap();assert.ok(back.conduits.every(c=>c.visible));
  assert.deepEqual(energyPlace(t.view.plan,[9999,9999,0]),null,'the yard is always shown');
 }finally{effect?.stop();t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('conduits are warm objects and dispose on satellite edits, anchor changes and stop',async()=>{
 const t=await conduitRig();let effect;try{
  t.live.stop();let warms=0;effect=mountEnergy({view:t.view,live:{layout:()=>t.layout,peek:()=>t.states,stale:()=>false},warm:()=>{warms++;}});
  effect.update('energy');await effect.ready();const conduits=()=>effect.warmObjects().filter(o=>o.userData.solarConduit||o.userData.solarConduitHalo);
  assert.equal(conduits().length,2);const old=conduits(),disposed=[];
  for(const resource of new Set(old.flatMap(o=>[o.geometry,o.material])))resource.addEventListener('dispose',()=>disposed.push(resource));
  const b=t.view.plan.buildings[0];b.solar_zones[1].rect=[12,-5,32,5];effect.update('energy');await effect.ready();
  assert.equal(disposed.length,3);assert.ok(old.every(o=>o.parent===null));assert.equal(warms,4);
  assert.ok(conduits().every(o=>!old.includes(o)));const next=conduits(),nextDisposed=[];
  for(const resource of new Set(next.flatMap(o=>[o.geometry,o.material])))resource.addEventListener('dispose',()=>nextDisposed.push(resource));
  b.position=[5,7];effect.update('all');await effect.ready();assert.equal(nextDisposed.length,3);assert.equal(warms,6);
  const last=conduits(),lastDisposed=[];for(const resource of new Set(last.flatMap(o=>[o.geometry,o.material])))resource.addEventListener('dispose',()=>lastDisposed.push(resource));
  effect.stop();effect=null;assert.equal(lastDisposed.length,3);assert.ok(last.every(o=>o.parent===null));
 }finally{effect?.stop();t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('mode warm-up sees conduits in both compile passes and does not rewarm on entry',async()=>{
 const t=await conduitRig();let modes;try{
  t.live.stop();t.view.tier='low';let passes=0;
  t.view.renderer3.compileAsync=async scene=>{let found=false;scene.traverse(o=>{if(o.userData.solarConduit)found ||= o.visible;});if(found)passes++;};
  const live={layout:()=>t.layout,peek:()=>t.states,state:id=>t.states[id],stale:()=>false,subscribe:()=>()=>{},rooms:()=>[],setMode(){}};
  modes=mountModes(t.view,live);await settleConduits(()=>modes.energy());assert.ok(passes>=2);const before=passes;t.view.onTimeLook();assert.equal(passes,before+2);
  for(const mode of ['energy','all','security','energy'])modes.setMode(mode);assert.equal(passes,before+2);
 }finally{modes?.stop();t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('opposite source slopes share a surface endpoint with the ribbon and retain it across power pushes',async()=>{
 const t=await conduitRig();let effect,roof;try{
  t.live.stop();t.view.scene.traverse(o=>{if(o.material?.name==='roof')o.material.name='floor';});
  const b=t.view.plan.buildings[0];b.roof.sections=[{...flatRoof(),rect:[-10,0,10,20],kind:'gable',ridge:'y',pitch:6},
   {...flatRoof(),id:'remote',rect:[10,0,20,20]}];
  b.solar_zones=[{id:'left',roof:'roof',plane:[.5,0,15],rect:[-8,2,-4,6]},
   {id:'right',roof:'roof',plane:[-.5,0,15],rect:[4,2,8,6]},
   {id:'sat',roof:'remote',plane:[0,0,10],rect:[12,2,16,6]}];
  const corners=[[[-10,0,10],[0,0,15],[0,20,15],[-10,20,10]],
   [[0,0,15],[10,0,10],[10,20,10],[0,20,15]],[[10,0,10],[20,0,10],[20,20,10],[10,20,10]]];
  const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(
   corners.flatMap(q=>[0,1,2,0,2,3].flatMap(i=>worldPoint(q[i]).toArray())),3));
  roof=new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({name:'roof'}));roof.userData.buildingId=b.id;t.view.scene.add(roof);
  effect=mountEnergy({view:t.view,live:{layout:()=>t.layout,peek:()=>t.states,stale:()=>false}});effect.update('energy');await effect.ready();
  const raw=energyAnchors(t.view,t.layout,{cars:[]}).solar,first=effect.snapshot();assert.equal(first.conduits.length,1);
  const end=first.conduits[0].source;assert.ok(worldPoint(end).distanceTo(worldPoint(raw))>FT);
  assert.deepEqual(first.anchors.solar,end);assert.deepEqual(first.ribbons.find(r=>r.id==='solar:house').from,end);
  const objects=effect.warmObjects();t.states['sensor.solar_power'].state='2000';effect.update('all');
  assert.deepEqual(effect.snapshot().anchors.solar,end);assert.deepEqual(effect.warmObjects(),objects);
 }finally{effect?.stop();roof?.removeFromParent();roof?.geometry.dispose();roof?.material.dispose();t.cleanup();t.panel.geometry.dispose();t.panel.material.dispose();}
});
check('threshold includes 50 W and width/speed scale',()=>{
 assert.equal(flowReading(49).visible,false);assert.equal(flowReading(-49).visible,false);assert.equal(flowReading(50).visible,true);
 assert.ok(flowReading(4000).width>flowReading(1000).width);assert.ok(flowReading(4000).speed>flowReading(1000).speed);
 for(const w of [0,50,1000,4000,100000])assert.ok(flowReading(w).width>=.4*FT && flowReading(w).width<=1.5*FT);
});
check('signed direction and kW labels',()=>{
 assert.equal(flowReading(-1500).direction,-1); assert.equal(flowReading(-1500).label,'1.5 kW');
 assert.equal(flowReading(-1500,false).direction,1);assert.equal(flowReading(2000,false).direction,-1);
});
check('solar layout is centred on the specified plane and has exact whole-panel count',()=>{
 const b={roof:{sections:[flatRoof()]},solar_zones:[{id:'z',roof:'roof',plane:[0,0,10],rect:[0,0,20,10]}]};
 const [{zone,panels}]=solarZones(b);assert.equal(panels.length,6);
 for(const r of panels)for(const p of solarRect(r)){const xyz=solarPoint(zone.plane,p,.15);assert.equal(xyz[2],10.15);assert.ok(p[0]>=0&&p[0]<=20&&p[1]>=0&&p[1]<=10);}
 assert.equal(solarLayout({...zone,orientation:'landscape'}).length,9);
 assert.equal(solarZones({...b,solar_zones:[]}).length,0);
});
check('mounted allocation responds to pushes, signs, threshold and presence',async()=>{
 const t=await energyRig({devices:[d('solar','sensor.solar_power',8000,power),d('battery','sensor.battery_power',-2000,power),
 d('grid','sensor.grid_power',-3000,power),d('house','sensor.house_power',3000,power),d('car','sensor.tesla_charge_power',1000,power),
 d('tracker','device_tracker.tesla_location','home'),d('level','sensor.tesla_battery',80,{device_class:'battery',unit_of_measurement:'%'})]});
 try{
  const bindings={chargers:[{id:'evse',name:'EV charger',power:'sensor.tesla_charge_power',car:'ev'}],cars:[{id:'ev',name:'EV',battery_level:'sensor.tesla_battery',location:'device_tracker.tesla_location'}]};t.live.configureEnergy({mapping:bindings,cars:[]});
  await press([...document.getElementById('twin-modes').querySelectorAll('button')].find(n=>n.textContent==='Energy'));
  let s=t.live.energy();const visible=()=>Object.fromEntries(t.live.energy().ribbons.filter(r=>r.visible).map(r=>[r.id,r.watts]));
  assert.deepEqual(visible(),{'solar:house':3000,'solar:battery':2000,'solar:grid':3000,'charger:0':1000});assert.equal(s.check.roles.find(r=>r.id==='charger:0').car,'ev');
  t.live.configureEnergy({mapping:{...bindings,home_includes_chargers:false},cars:[]});
  assert.deepEqual(visible(),{'solar:house':4000,'solar:battery':2000,'solar:grid':2000,'charger:0':1000});
  t.live.configureEnergy({mapping:{...bindings,home_includes_chargers:true},cars:[]});
  const grid=[];t.view.scene.traverse(o=>{if(o.userData.energyRibbon==='grid:house')grid.push(o);}); const geometry=grid[0].geometry,material=grid[0].material;
  t.states['sensor.solar_power'].state='1000';t.states['sensor.battery_power'].state='2000';t.states['sensor.grid_power'].state='2500';t.states['sensor.house_power'].state='5500';
  t.states['sensor.tesla_charge_power'].state='40';t.states['device_tracker.tesla_location'].state='away';await t.live.refresh();
  s=t.live.energy();assert.deepEqual(visible(),{'solar:house':1000,'battery:house':2000,'grid:house':2500});assert.equal(s.check.roles.find(r=>r.id==='charger:0').car,null);
  assert.equal(grid[0].geometry,geometry);assert.equal(grid[0].material,material);assert.equal(t.live.marker('solar').dim,false);
  t.states['sensor.battery_power'].state='-2000';t.states['sensor.grid_power'].state='-2500';
  t.live.configureEnergy({mapping:{battery_positive:'charge',grid_positive:'export',cars:[],chargers:[]},cars:[]});await t.live.refresh();
  assert.deepEqual(visible(),{'solar:house':1000,'battery:house':2000,'grid:house':2500});
 }finally{t.cleanup();}
});
check('battery export and grid charging swap flows with exact anchors and retained programs',async()=>{
 const t=await energyRig({devices:[d('solar','sensor.solar_power',0,power),d('battery','sensor.battery_power',6000,power),d('grid','sensor.grid_power',-4000,power),d('house','sensor.house_power',2000,power)]});
 try{
  t.live.setMode('energy');const meshes=[];t.view.scene.traverse(o=>{if(o.userData.energyRibbon || o.userData.energyRibbonHalo)meshes.push([o,o.geometry,o.material,o.material.customProgramCacheKey()]);});
  const visible=()=>Object.fromEntries(t.live.energy().ribbons.filter(r=>r.visible).map(r=>[r.id,r.watts]));
  assert.deepEqual(visible(),{'battery:house':2000,'battery:grid':4000});
  const assertEndpoints=()=>{const s=t.live.energy();for(const row of s.ribbons){const [from,to]=row.id.split(':');assert.deepEqual(row.from,s.anchors[from]);assert.deepEqual(row.to,s.anchors[to]);assert.equal(row.direction,1);}};
  assertEndpoints();t.states['sensor.battery_power'].state='-5000';t.states['sensor.grid_power'].state='7000';await t.live.refresh();
  assert.deepEqual(visible(),{'grid:house':2000,'grid:battery':5000});assertEndpoints();
  for(const [o,g,m,k]of meshes){assert.equal(o.geometry,g);assert.equal(o.material,m);assert.equal(m.customProgramCacheKey(),k);assert.ok(o.parent);}
  const allocation=t.live.energy().ribbons.find(r=>r.id==='grid:battery');assert.equal(allocation.label,'5 kW');
 }finally{t.cleanup();}
});
check('zone and panel geometry never bridge exposed roof cutouts',()=>{
 const b={roof:{sections:[flatRoof(),{...flatRoof(),id:'upper',rect:[5,0,7,20],plate:20}]},solar_zones:[{id:'z',roof:'roof',plane:[0,0,10],rect:[0,0,20,10]}]};
 const plane=solarPlanes(b).find(p=>p.roof==='roof');assert.equal(solarCovered([0,0,20,10],plane),false);assert.equal(solarZones(b).length,0);
 b.solar_zones[0].rect=[10,0,30,10];const zones=solarZones(b);assert.equal(zones[0].panels.length,6);
 for(const rect of zones[0].panels)assert.ok(solarCovered(rect,plane));
});
check('mode re-entry reuses all materials, geometries and program keys',async()=>{
 const t=await energyRig({devices:[d('solar','sensor.solar_power',4000,power)]});
 try{
  t.live.setMode('energy');const rows=[]; t.view.scene.traverse(o=>{if(o.material)rows.push([o,o.material,o.geometry,o.material.customProgramCacheKey()]);});
  for(let i=0;i<3;i++){t.live.setMode('security');t.live.setMode('all');t.live.setMode('energy');}
  for(const [o,m,g,k] of rows){assert.equal(o.material,m);assert.equal(o.geometry,g);assert.equal(m.customProgramCacheKey(),k);}
 }finally{t.cleanup();}
});
check('ribbon has a continuous emissive core and soft additive halo reused for power and sign changes',async()=>{
 const t=await energyRig({devices:[d('battery','sensor.battery_power',2000,power),d('house','sensor.house_power',8000,power)]});
 try{
  t.live.setMode('energy');let core,halo;t.view.scene.traverse(o=>{if(o.userData.energyRibbon==='battery:house')core=o;if(o.userData.energyRibbonHalo==='battery:house')halo=o;});
  assert.ok(core.visible && halo.visible);assert.equal(halo.material.blending,THREE.AdditiveBlending);
  for(const material of [core.material,halo.material]){assert.equal(material.depthTest,false);assert.equal(material.depthWrite,false);}
  assert.ok(core.renderOrder>halo.renderOrder && halo.renderOrder>20);assert.equal(core.material.toneMapped,false);
  assert.ok(core.material.uniforms.coreGain.value<=1);assert.ok(halo.material.uniforms.edgeAlpha.value<=.6);
  assert.equal(core.material.uniforms.color.value.getHex(),new THREE.Color(FLOW_COLORS.battery).getHex());
  assert.equal(core.geometry,halo.geometry);const geometry=core.geometry,material=core.material;
  const oldWidth=core.material.uniforms.radius.value;t.states['sensor.battery_power'].state='4000';await t.live.refresh();
  assert.ok(core.material.uniforms.radius.value>oldWidth);assert.equal(core.geometry,geometry);assert.equal(core.material,material);
  t.live.configureEnergy({mapping:{battery_positive:'charge',panels:{visible:false}},cars:[]});
  assert.equal(core.geometry,geometry);assert.equal(core.parent!==null,true);assert.equal(core.material,material);
  assert.equal(core.visible,false);t.states['sensor.battery_power'].state='-4000';await t.live.refresh();assert.equal(core.visible,true);
  const phase=core.material.uniforms.phase.value;await wait(20);t.live.draw();assert.notEqual(core.material.uniforms.phase.value,phase);
  assert.equal(core.material.uniforms.phase.value,halo.material.uniforms.phase.value);
 }finally{t.cleanup();}
});
check('crowded labels all remain visible, try their ribbon, then stack with a gap',()=>{
 const placed=flowLabelPositions(Array.from({length:8},()=>({x:700,y:400,width:130})),{left:0,right:1400});
 assert.ok(placed.every(p=>p.visible));
 const shown=placed.filter(p=>p.visible);
 for(let i=0;i<shown.length;i++)for(let j=0;j<i;j++){
  const a=shown[i],b=shown[j];assert.ok(!(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top));
 }
 const separate=flowLabelPositions([{x:300,y:400,width:130},{x:700,y:400,width:130}],{left:0,right:1400});
 assert.ok(separate.every(p=>p.visible));assert.deepEqual(separate.map(p=>[p.x,p.y]),[[300,400],[700,400]]);
 const pair=flowLabelPositions([{x:700,y:400,width:130},{x:700,y:400,width:130}],{left:0,right:1400});
 assert.ok(pair.every(p=>p.visible));assert.ok(Math.abs(pair[0].y-pair[1].y)>=26);
 const along=flowLabelPositions([{x:700,y:400,width:130},{x:700,y:400,width:130,along:[{x:900,y:420}]}],{left:0,right:1400});
 assert.deepEqual([along[1].x,along[1].y],[900,420]);
 const edge=flowLabelPositions(Array.from({length:8},()=>({x:10,y:-100,width:130})),{left:0,right:1400,top:0,bottom:1000});
 assert.ok(edge.every(p=>p.visible&&p.left>=0&&p.top>=0&&p.bottom<=1000),'offscreen apexes retain readable labels inside the viewport');
});
check('real household zones draw with physical depth in every mode and actual centroid',async()=>{
 const {buildTwin}=await import(file('static/twin/twin_generator.js'));
 const plan=structuredClone(config.harness_plan);let placed=null;
 for(const b of plan.buildings){for(const p of solarPlanes(b)){
  const uv=p.triangles.flat(),xs=uv.map(p=>p[0]),ys=uv.map(p=>p[1]);
  for(let y=Math.min(...ys)+1;y+6<Math.max(...ys)&&!placed;y+=2)for(let x=Math.min(...xs)+1;x+4<Math.max(...xs)&&!placed;x+=2){
   const rect=[x,y,x+4,y+6];if(solarCovered(rect,p)){b.solar_zones=[{id:'test-zone',roof:p.roof,plane:p.plane,rect}];plan.solar_source_roof=p.roof;placed={b,p,rect};}
  }if(placed)break;
 }if(placed)break;}
 assert.ok(placed);const twin=buildTwin(plan,{materials:{}},'low');await twin.ready;
 try{const objects=twin.pieces.get(placed.b.id+':test-zone');assert.ok(objects?.length);for(const o of objects){assert.equal(o.material.depthTest,true);assert.equal(o.material.depthWrite,true);assert.equal(o.material.transparent,false);}
  const a=energyAnchors({plan},{markers:[]},{cars:[]}),r=placed.rect;
  const expected=lotPoint(placed.b,solarPoint(placed.p.plane,[(r[0]+r[2])/2,(r[1]+r[3])/2],.15),plan);assert.ok(a.solar.every((v,i)=>Math.abs(v-expected[i])<1e-10));assert.equal(a.house,null);assert.equal(a.grid,null);
 }finally{twin.root.traverse(o=>{o.geometry?.dispose();for(const m of o.material?[].concat(o.material):[])m.dispose();});}
});
check('arcs preserve coincident and short endpoint coordinates exactly',()=>{
 for(const end of [[0,0,0],[1,1,8],[2.9,0,0]]){
  const route=flowRoute([0,0,0],end,3,'to'),curve=flowCurve(route.from,route.to,10);
  assert.deepEqual(route.from,[0,0,0]);assert.deepEqual(route.to,end);assert.ok(curve.isQuadraticBezierCurve3);
  assert.ok(curve.getPoint(0).distanceTo(worldPoint(route.from))<1e-9);assert.ok(curve.getPoint(1).distanceTo(worldPoint(end))<1e-9);
  const a=curve.v0,b=curve.v2;for(const p of curve.getPoints(15))assert.ok(Math.abs((p.x-a.x)*(b.z-a.z)-(p.z-a.z)*(b.x-a.x))<1e-7);
 }
});
check('actual apex uses the gentle span formula, including short spans and unequal endpoints',()=>{
 for(const span of [0,1,3.9,4,8,20,100])for(const heights of [[0,0],[2,9],[15,1]]){
  const from=[0,0,heights[0]],to=[span,0,heights[1]],curve=flowCurve(from,to),apex=flowApex(curve);
  const rise=span<4?2+span/4:Math.max(3,Math.min(10,.3*span));
  assert.ok(Math.abs(apex.y/FT-Math.max(...heights)-rise)<1e-9,[span,heights,apex.y/FT]);
  for(const p of curve.getPoints(200))assert.ok(p.y<=apex.y+1e-9);
  assert.ok(curve.getPoint(0).distanceTo(worldPoint(from))<1e-10);assert.ok(curve.getPoint(1).distanceTo(worldPoint(to))<1e-10);
 }
});
check('shared starts and ends fan deterministically by id, at least two maximum ribbon widths apart',()=>{
 const width=flowReading(4000).width;
 for(const reversed of [false,true]){
  const rows=[{id:'grid:house',from:[0,0,4],to:[20,0,4]},{id:'grid:battery',from:[0,0,4],to:[21,0,4]}]
   .map(r=>reversed?{...r,from:r.to,to:r.from}:r);
  const fans=flowFans(rows,width),again=flowFans([...rows].reverse(),width);
  for(const row of rows)assert.deepEqual(fans.get(row.id),again.get(row.id));
  const curves=rows.map(row=>flowCurve(row.from,row.to,fans.get(row.id))),apexes=curves.map(flowApex);
  assert.ok(apexes[0].distanceTo(apexes[1])>=2*width);
  assert.ok(Math.abs(fans.get(rows[0].id).tilt)*180/Math.PI>=10);assert.ok(Math.abs(fans.get(rows[0].id).tilt)*180/Math.PI<=15);
  for(const curve of curves){
   const normal=curve.v1.clone().sub(curve.v0).cross(curve.v2.clone().sub(curve.v0)).normalize();
   for(const p of curve.getPoints(30))assert.ok(Math.abs(p.clone().sub(curve.v0).dot(normal))<1e-9,'fanned curves stay planar');
  }
 }
});
check('every member of two- and three-flow shared groups has a non-zero fan offset',()=>{
 const width=flowReading(4000).width;
 for(const n of [2,3]){
  const rows=Array.from({length:n},(_,i)=>({id:'grid:'+i,from:[0,0,4],to:[20+i,0,4]})),fans=flowFans(rows,width);
  for(const row of rows){
   assert.notEqual(fans.get(row.id).offset,0,row.id);
   const natural=flowApex(flowCurve(row.from,row.to)),fanned=flowApex(flowCurve(row.from,row.to,fans.get(row.id)));
   assert.ok(natural.distanceTo(fanned)>=width,row.id+' actually moves');
  }
  if(n===2)assert.equal(fans.get(rows[0].id).offset,-fans.get(rows[1].id).offset);
 }
});
// Intersect every sampled xz segment, with independent parameters on the two
// curves: comparing only points at matching t misses unequal-length crossings.
function groundTracksCross(a,b,shared){
 const eps=1e-9,cross=(a,b)=>a.x*b.z-a.z*b.x,sub=(a,b)=>({x:a.x-b.x,z:a.z-b.z});
 const atShared=p=>Math.hypot(p.x-shared.x,p.z-shared.z)<eps;
 for(let i=1;i<a.length;i++)for(let j=1;j<b.length;j++){
  const p=a[i-1],q=b[j-1],r=sub(a[i],p),s=sub(b[j],q),delta=sub(q,p),den=cross(r,s);
  if(Math.abs(den)>1e-12){
   const t=cross(delta,s)/den,u=cross(delta,r)/den;
   if(t>=-eps&&t<=1+eps&&u>=-eps&&u<=1+eps&&!atShared({x:p.x+t*r.x,z:p.z+t*r.z}))return true;
  }else if(Math.abs(cross(delta,r))<1e-12){
   const axis=Math.abs(r.x)>Math.abs(r.z)?'x':'z';if(Math.abs(r[axis])<1e-12)continue;
   const low=Math.max(Math.min(p[axis],a[i][axis]),Math.min(q[axis],b[j][axis]));
   const high=Math.min(Math.max(p[axis],a[i][axis]),Math.max(q[axis],b[j][axis]));
   if(high-low>eps)return true;
   if(high>=low-eps){const t=(low-p[axis])/r[axis];if(!atShared({x:p.x+t*r.x,z:p.z+t*r.z}))return true;}
  }
 }
 return false;
}
const solarFanRows=(angles,lengths,rotation=0)=>angles.map((angle,i)=>{
 const a=(angle+rotation)*Math.PI/180;
 return {id:['solar:grid','solar:house','solar:battery','solar:charger'][i],from:[0,0,12],
  to:[Math.cos(a)*lengths[i],-Math.sin(a)*lengths[i],4+i]};
});
function assertGroundFan(rows){
 const width=flowReading(4000).width,fans=flowFans(rows,width),again=flowFans([...rows].reverse(),width);
 const tracks=rows.map(row=>flowCurve(row.from,row.to,fans.get(row.id)).getPoints(160));
 for(const row of rows){assert.deepEqual(fans.get(row.id),again.get(row.id));assert.notEqual(fans.get(row.id).offset,0);}
 for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++)
  assert.equal(groundTracksCross(tracks[i],tracks[j],worldPoint([0,0,12])),false,rows[i].id+' crosses '+rows[j].id);
 return fans;
}
check('solar fans two nearby targets without crossing while the third heads away',()=>{
 const width=flowReading(4000).width,rows=solarFanRows([160,0,20],[30,28,18]);
 // Prove the intersection check sees the original swapped-lane failure.
 const swapped=rows.slice(1).map((row,i)=>flowCurve(row.from,row.to,
  {offset:(i?-1:1)*1.5*width,tilt:(i?-1:1)*Math.PI/15}).getPoints(160));
 assert.equal(groundTracksCross(...swapped,worldPoint(rows[0].from)),true);
 for(const rotation of [0,175,-70])for(const reverse of [false,true]){
  const rows=solarFanRows([160,0,20],[30,28,18],rotation).map((row,i)=>reverse&&i!==1?{...row,from:row.to,to:row.from}:row);
  const fans=assertGroundFan(rows);
  for(const row of rows.slice(1))assert.ok(flowApex(flowCurve(row.from,row.to,fans.get(row.id)))
   .distanceTo(flowApex(flowCurve(row.from,row.to)))>1e-6,'both nearby routes actually fan');
 }
});
check('adding a fourth ribbon preserves non-crossing pairs across unequal spans and reversed ends',()=>{
 for(const a of [8,20,60])for(const b of [8,20,60])for(const c of [8,20,60])
  for(const angles of [[160,0,20,10],[0,10,20,30]])for(const rotation of [0,175]){
   const rows=solarFanRows(angles,[30,a,b,c],rotation).map((row,i)=>i%2?{...row,from:row.to,to:row.from}:row);
   assertGroundFan(rows.slice(0,3));assertGroundFan(rows);
  }
});
check('collinear fans nest same-side lanes without crossing when a fourth route is added',()=>{
 for(const lengths of [[20,21,22,23],[60,8,20,9],[8,60,9,20],[20,20.1,20.2,20.3]]){
  const rows=solarFanRows([0,0,0,0],lengths);
  assertGroundFan(rows.slice(0,3));assertGroundFan(rows);
 }
});
check('reverse transfers share one physical fan lane while independent same-direction routes still fan',()=>{
 const anchors={battery:[-16,4,2],grid:[-8,4,2],house:[0,4,2]},width=flowReading(4000).width;
 const rows=energyTopology(anchors,{cars:[]}),fans=flowFans(rows,width),again=flowFans([...rows].reverse(),width);
 for(const row of rows)assert.deepEqual(fans.get(row.id),again.get(row.id));
 assert.deepEqual(fans.get('grid:battery'),fans.get('battery:grid'));
 const curves=['grid:battery','battery:grid'].map(id=>{const row=rows.find(r=>r.id===id);return flowCurve(row.from,row.to,fans.get(id));});
 for(let i=0;i<=100;i++)assert.ok(curves[0].getPoint(i/100).distanceTo(curves[1].getPoint(1-i/100))<1e-9);
 const parallel=[{id:'a',from:[0,0,4],to:[20,0,4]},{id:'b',from:[0,0,4],to:[20,0,4]}],lanes=flowFans(parallel,width);
 assert.notEqual(lanes.get('a').offset,0);assert.equal(lanes.get('a').offset,-lanes.get('b').offset);
});
check('collinear topology nests lanes consistently when routes share both fan ends',()=>{
 const permutations=xs=>xs.length?xs.flatMap((x,i)=>permutations(xs.filter((_,j)=>j!==i)).map(rest=>[x,...rest])):[[]];
 for(const positions of permutations([0,8,16,24])){
  const anchors=Object.fromEntries(['solar','battery','grid','house'].map((role,i)=>[role,[positions[i],0,4]]));
  // Keep one representative of the mutually exclusive battery/grid pair.
  const rows=energyTopology(anchors,{cars:[]}).filter(r=>r.id!=='grid:battery'),fans=flowFans(rows,flowReading(4000).width);
  const tracks=rows.map(r=>flowCurve(r.from,r.to,fans.get(r.id)).getPoints(160));
  for(let i=0;i<rows.length;i++)for(let j=i+1;j<rows.length;j++){
   const a=rows[i],b=rows[j],shared=[a.from,a.to].find(p=>[b.from,b.to].some(q=>JSON.stringify(p)===JSON.stringify(q)));
   if(shared)assert.equal(groundTracksCross(tracks[i],tracks[j],worldPoint(shared)),false,positions+': '+a.id+' crosses '+b.id);
  }
 }
});
check('rendered mesh cross-sections use the full 0.4–1.5ft power width and a soft halo',async()=>{
 const t=await energyRig({devices:[d('grid','sensor.grid_power',50,power),d('house','sensor.house_power',50,power)]});
 try{
  t.live.setMode('energy');let core,halo;t.view.scene.traverse(o=>{if(o.userData.energyRibbon==='grid:house')core=o;if(o.userData.energyRibbonHalo==='grid:house')halo=o;});
  const geometry=core.geometry,material=core.material;
  for(const watts of [0,50,500,1500,4000,100000]){
   t.states['sensor.grid_power'].state=t.states['sensor.house_power'].state=String(watts);await t.live.refresh();
   const width=flowReading(watts).width,positions=core.geometry.attributes.position,centres=core.geometry.attributes.centerline;
   assert.ok(centres,'actual mesh positions are centred on the curve, not contracted from a 1m tube in the shader');
   assert.ok(width>=.4*FT&&width<=1.5*FT);assert.equal(core.geometry,geometry);assert.equal(core.material,material);
   for(let i=0;i<positions.count;i++){
    const radius=new THREE.Vector3().fromBufferAttribute(positions,i).distanceTo(new THREE.Vector3().fromBufferAttribute(centres,i));
    assert.ok(Math.abs(2*radius-width)<1e-5,[watts,i,2*radius,width]);
   }
   assert.equal(core.material.uniforms.radius.value,width/2);assert.equal(halo.material.uniforms.radius.value,width);
   assert.equal(halo.material.blending,THREE.AdditiveBlending);assert.ok(halo.material.uniforms.edgeAlpha.value>0);
  }
 }finally{t.cleanup();}
});
check('the real pool-house meter, panel and battery placements fan both grid flows apart',async()=>{
 const {hostPoint}=await import(file('static/twin/twin_hosts.js'));
 const plan=structuredClone(config.harness_plan),b=plan.buildings.find(b=>b.id==='pool-house');
 const wall='wall:17ec2a8dad9e47d0aefbfe143524c1c2~2';assert.ok(b.walls.some(w=>w.id===wall));
 b.anchors=[{id:'meter',kind:'meter',host:{wall,side:'right',at:2.5,z:4}},
  {id:'panel',kind:'electric_panel',host:{wall,side:'left',at:15,z:4}}];
 const mapping={battery_power:'sensor.live_battery',grid_power:'sensor.live_grid',house_power:'sensor.live_house',cars:[],
  locations:{battery:{type:'device',id:'battery'},grid:{type:'object',building:b.id,id:'meter'},house:{type:'object',building:b.id,id:'panel'}}};
 const at=lotPoint(b,hostPoint(b,{floor:'room:5d7de10ca48340ae85c407d22337c6f7',u:.35,v:.65},4),plan);
 const layout={markers:[{device_id:'battery',entity_id:'sensor.live_battery',building:b.id,placed:true,at}]};
 const anchors=energyAnchors({plan},layout,mapping),rows=energyTopology(anchors,mapping),width=flowReading(4000).width,fans=flowFans(rows,width);
 const grid=rows.filter(r=>r.id==='grid:house'||r.id==='grid:battery');assert.equal(grid.length,2);
 const apexes=grid.map(r=>{assert.notEqual(fans.get(r.id).offset,0);return flowApex(flowCurve(r.from,r.to,fans.get(r.id)));});
 assert.ok(apexes[0].distanceTo(apexes[1])>=2*width,'actual house placements separate by two maximum widths');
});
check('mounted grid fan labels anchor to their own apex and reproject on camera movement',async()=>{
 const t=await energyRig({devices:[d('solar','sensor.solar_power',0,power),d('battery','sensor.battery_power',-2000,power),
  d('grid','sensor.grid_power',2500,power),d('house','sensor.house_power',500,power)]});
 try{
  t.live.setMode('energy');t.live.draw();
  const rows=t.live.energy().ribbons.filter(r=>r.visible);assert.deepEqual(rows.map(r=>r.id).sort(),['grid:battery','grid:house']);
  assert.ok(new THREE.Vector3().fromArray(rows[0].apex).distanceTo(new THREE.Vector3().fromArray(rows[1].apex))>=2*Math.max(...rows.map(r=>r.width)));
  for(const row of rows){let mesh;t.view.scene.traverse(o=>{if(o.userData.energyRibbon===row.id)mesh=o;});
   assert.deepEqual(row.apex,flowApex(mesh.geometry.parameters.path).toArray());assert.deepEqual(row.labelAnchor,row.apex);}
  const before=rows.map(r=>document.querySelector('[data-energy-label="'+r.id+'"]').style.left);
  t.camera.position.set(10,45,10);t.camera.lookAt(0,0,0);t.camera.updateMatrixWorld(true);t.live.draw();
  const after=rows.map(r=>document.querySelector('[data-energy-label="'+r.id+'"]').style.left);assert.notDeepEqual(after,before);
  assert.equal(rows.filter(r=>!document.querySelector('[data-energy-label="'+r.id+'"]').hidden).length,2,'both fan labels fit after camera movement');
  for(const row of rows){const node=document.querySelector('[data-energy-label="'+row.id+'"]');if(node.hidden)continue;
   const p=new THREE.Vector3().fromArray(row.apex).project(t.camera);
   assert.ok(Math.hypot(parseFloat(node.style.left)-(p.x+1)*700,parseFloat(node.style.top)-(1-p.y)*500)<=24+1e-9);}
 }finally{t.cleanup();}
});
check('ribbons draw over roofs with no mask, offscreen render, or extra warm-up pass',async()=>{
 const t=await energyRig({devices:[d('grid','sensor.grid_power',1800,power),d('house','sensor.house_power',1800,power)]});
 let effect;
 try{
  t.live.stop();t.view.groups.roof=new THREE.Group();
  t.view.roofSurfaces=new Map([['b',{positions:[-5,-5,10,5,-5,10,0,5,10]}]]);
  let renders=0,compiles=0,targetChanges=0;
  Object.assign(t.view.renderer3,{getRenderTarget:()=>null,setRenderTarget:()=>{targetChanges++;},getDrawingBufferSize:v=>v.set(1400,1000),
   getClearColor:v=>v.set('#182030'),getClearAlpha:()=>1,setClearColor(){},render:()=>{renders++;},compileAsync:async()=>{compiles++;}});
  const live={layout:()=>t.layout,peek:()=>t.states,stale:()=>false};
  effect=mountEnergy({view:t.view,live});effect.update('energy');
  assert.equal(energyModule.createRoofFade,undefined);
  for(const mode of ['all','energy','energy','all','energy']){t.view.camera.position.x++;effect.draw(mode);effect.warm?.();}
  t.view.groups.roof.visible=false;effect.draw('energy');
  t.view.roofSurfaces=new Map(t.view.roofSurfaces);effect.update('energy');effect.draw('energy');
  assert.equal(renders,0,'the main scene owns the only render pass');
  assert.equal(compiles,0,'no separate depth shader needs warming');assert.equal(targetChanges,0,'no offscreen target is used');
  const ribbons=[];t.view.scene.traverse(o=>{if(o.userData.energyRibbon||o.userData.energyRibbonHalo)ribbons.push(o);});
  assert.ok(ribbons.length>0);assert.ok(effect.snapshot().ribbons.some(r=>r.visible));
  for(const o of ribbons){assert.equal(o.material.depthTest,false);assert.equal(o.material.depthWrite,false);assert.ok(o.renderOrder>20);
   assert.equal(o.material.uniforms.roofDepth,undefined);assert.doesNotMatch(o.material.fragmentShader,/roofDepth|roofFade|sampler2D/);}
 }finally{effect?.stop();t.cleanup();}
});
check('warm path sees chargers for away cars and cones before entry and on time look',async()=>{
 const t=await energyRig({devices:[d('car','sensor.tesla_charge_power',1000,power),d('tracker','device_tracker.tesla_location','away'),d('camera','camera.k','idle',{},'camera')]});
 let extra;
 try{
  t.live.stop(); t.view.tier='low'; let warms=0,sawCar=false,sawCone=false;
  t.view.renderer3.compileAsync=async(scene)=>{warms++;scene.traverse(o=>{if(o.userData.energyRibbon==='charger:0')sawCar ||= o.visible;if(o.userData.cameraCone)sawCone ||= o.visible;});};
  const live={layout:()=>t.layout,peek:()=>t.states,state:id=>t.states[id],stale:()=>false,subscribe:()=>()=>{},rooms:()=>[],setMode(){}};
  t.view.energySources={mapping:{cars:[],chargers:[{id:'evse',name:'EVSE',power:'sensor.tesla_charge_power'}]},cars:[]};
  extra=mountModes(t.view,live);assert.ok(warms>0);assert.ok(sawCar);assert.ok(sawCone);
  // One warm-up compiles twice: with the pool shown (Lights, All) and hidden (the other modes).
  const before=warms;t.view.onTimeLook();assert.equal(warms,before+2);
  extra.setMode('energy');extra.setMode('all');extra.setMode('energy');assert.equal(warms,before+2);
 }finally{extra?.stop();t.cleanup();}
});
check('all placed-role combinations obey topology and placement legend',()=>{
 const mapping={battery_power:'sensor.battery',cars:[],chargers:[{id:'evse',name:'the charger',power:'sensor.ev'}]};
 for(let mask=0;mask<32;mask++){
  const a={solar:mask&1?[1,2,3]:null,battery:mask&2?[4,5,6]:null,house:mask&4?[7,8,9]:null,grid:mask&8?[10,11,12]:null,chargers:[mask&16?[13,14,15]:null]};
  const rows=energyTopology(a,mapping),ids=rows.map(r=>r.id);
  for(const [source,target] of [['solar','house'],['solar','battery'],['solar','grid'],['battery','house'],['grid','house'],['grid','battery'],['battery','grid']])
   assert.equal(ids.includes(source+':'+target),!!(a[source]&&a[target]));
  assert.equal(ids.includes('charger:0'),!!(a.house&&a.chargers[0]));
  for(const row of rows){const [source,target]=row.id.split(':');assert.deepEqual(row.from,source==='charger'?a.house:a[source]);assert.deepEqual(row.to,source==='charger'?a.chargers[Number(target)]:a[target]);}
  const legend=energyPlacementLegend(a,mapping);assert.equal(legend.includes('Place the meter'),!a.grid);assert.equal(legend.includes('Place the electric panel'),!a.house);assert.equal(legend.includes('Place the charger'),!a.chargers[0]);
 }
});
check('locations match only placed power entities and removed references never guess',async()=>{
 const t=await energyRig({devices:[d('bat','sensor.powerwall_battery_power',1000,power)]});
 try{const m={battery_power:'sensor.powerwall_battery_power',house_power:'sensor.house_power',cars:[]};
  assert.deepEqual(energyAnchors(t.view,t.layout,m).battery,t.layout.markers[0].at);
  assert.equal(energyAnchors(t.view,t.layout,{...m,locations:{battery:null}}).battery,null);
  assert.equal(energyAnchors(t.view,t.layout,{...m,locations:{battery:{type:'device',id:'removed'}}}).battery,null);
  assert.equal(energyAnchors(t.view,{markers:[]},m).grid,null);
  t.layout.markers[0].location_valid=false;assert.equal(energyAnchors(t.view,t.layout,m).battery,null);
 }finally{t.cleanup();}
});
check('plain equipment positions include the wall side, building rotation, base and ground',()=>{
 const b={id:'b',position:[10,20],rotation:90,base:3,levels:[{id:'L1',elevation:2}],walls:[{id:'w',level:'L1',from:[0,0],to:[20,0],thickness:.5}],anchors:[{id:'meter',kind:'meter',host:{wall:'w',side:'right',at:5,z:4}},{id:'panel',kind:'electric_panel',host:{wall:'w',side:'left',at:15,z:5}}]};
 const view={plan:{buildings:[b]}},mapping={locations:{grid:{type:'object',id:'meter',building:'b'},house:{type:'object',id:'panel',building:'b'}},cars:[]};
 const a=energyAnchors(view,{markers:[]},mapping);assert.deepEqual(a.grid,lotPoint(b,[5,-.29,6],view.plan));assert.deepEqual(a.house,lotPoint(b,[15,.29,7],view.plan));
 b.anchors=b.anchors.slice(1);const gone=energyAnchors(view,{markers:[]},mapping);assert.equal(gone.grid,null);assert.equal(energyTopology(gone,mapping).some(r=>r.id.split(':').includes('grid')),false);assert.ok(energyPlacementLegend(gone,mapping).includes('Place the meter'));
});
check('multiple roofs require a source and source zones use their area-weighted centroid',()=>{
 const sections=[flatRoof(),{...flatRoof(),id:'other',rect:[100,0,140,20],plate:12}];
 const b={id:'b',roof:{sections},solar_zones:[{roof:'roof',plane:[0,0,10],rect:[0,0,20,10]},{roof:'roof',plane:[0,0,10],rect:[20,0,30,10]},{roof:'other',plane:[0,0,12],rect:[100,0,120,10]}]};
 const view={plan:{buildings:[b]}};assert.equal(energyAnchors(view,{markers:[]},{cars:[]}).solar,null);
 view.plan.solar_source_roof='roof';const a=energyAnchors(view,{markers:[]},{cars:[]});assert.deepEqual(a.solar,[15,5,10.15]);
});
check('drawer loads, edits a sign, saves and applies the mapping',async()=>{
 const {mountEnergySettings}=await import(file('static/twin/live/energy_settings.js'));
 const fields=document.createElement('div');fields.id='twin-energy-fields';document.body.append(fields);
 const button=document.createElement('button');button.id='twin-energy-save';document.body.append(button);
 let stored={},writes=0,applied;
 const view={live:{peek:()=>({'sensor.solar_power':{state:'4000',attributes:power}}),configureEnergy:p=>{applied=p;}},glance:{energy(){}}};
 const settings=mountEnergySettings(view,{api:async(path,init)=>{if(init){writes++;stored=JSON.parse(init.body);}return {ok:true,json:async()=>({mapping:stored,cars:[],can_edit:true})};}});
 try{await settings.reload();assert.ok(fields.querySelectorAll('select').length>=7);const sign=fields.querySelectorAll('label').find(n=>n.textContent.startsWith('Positive battery power means')).querySelector('select');sign.value='charge';sign.dispatchEvent(new Event('change'));const flag=fields.querySelectorAll('label').find(n=>n.textContent.includes('Home power includes car chargers')).querySelector('input');assert.equal(flag.checked,true);flag.checked=false;flag.dispatchEvent(new Event('change'));await press(button);await wait(20);assert.equal(stored.home_includes_chargers,false);assert.equal(applied.mapping.home_includes_chargers,false);assert.equal(writes,1);assert.equal(stored.battery_positive,'charge');assert.equal(applied.mapping.battery_positive,'charge');}
 finally{settings.stop();fields.remove();button.remove();}
});
check('mapping changes reconnect stream scope and accept custom sensor pushes',async()=>{
 const previous=globalThis.EventSource,sources=[];
 globalThis.EventSource=class{constructor(){this.closed=false;sources.push(this);}close(){this.closed=true;}};
 let t;try{
  t=await energyRig({devices:[d('light','light.a','off',{},'light')]});const before=sources.length;
  const preferences={mapping:{solar_power:'sensor.unusual'},cars:[]};
  t.live.configureEnergy(preferences);assert.equal(sources.length,before+1);assert.equal(sources[before-1].closed,true);
  t.live.configureEnergy(preferences);assert.equal(sources.length,before+1);
  t.live.setMode('energy');t.view.energySources={mapping:{solar_power:'sensor.unusual',house_power:'sensor.house_power'},cars:[]};sources.at(-1).onmessage({data:JSON.stringify({entity_id:'sensor.unusual',state:{state:'1500',attributes:{unit_of_measurement:'W'}}})});
  await wait(40);assert.equal(t.live.energy().ribbons.find(r=>r.id==='solar:house').label,'0.5 kW');assert.equal(t.live.energy().ribbons.find(r=>r.id==='solar:house').visible,true);
 }finally{t?.cleanup();globalThis.EventSource=previous;}
});
check('mapping refresh and keeper remount keep one of each mode overlay and dispose the old nodes',async()=>{
 const t=await rig({devices:[d('climate','climate.k','heat',{current_temperature:80,temperature:68},'climate'),d('camera','camera.k','idle',{},'camera')]});
 t.live.stop();
 let layout=structuredClone(t.layout);
 const api=async path=>({ok:true,json:async()=>structuredClone(path==='api/house/live'?layout:{states:t.states})});
 const keeper=liveModule.keepLive(t.view,{api});
 const unique=()=>{
  for(const selector of ['.twin-climate-labels','.twin-energy-labels','#twin-modes','#twin-mode-legend','.twin-live-labels','#twin-room-panel','.twin-device-sheet:not(#twin-room-panel)'])assert.equal(document.querySelectorAll(selector).length,1,selector);
  const owners=[];t.view.scene.traverse(o=>{if(o.userData.twinMode)owners.push(o.userData.twinMode);});
  assert.deepEqual(owners.sort(),['energy','modes','security']);
 };
 try{
  await keeper.check();t.view.live.setMode('climate');unique();
  const first=t.view.live,oldLabels=document.querySelector('.twin-climate-labels'),oldEnergy=document.querySelector('.twin-energy-labels');
  for(let i=0;i<3;i++)first.configureEnergy({mapping:{solar_power:'sensor.solar'},cars:[]});
  assert.equal(t.view.live,first);unique();
  layout.markers[0].at[0]+=1;await keeper.check();
  assert.notEqual(t.view.live,first);t.view.live.setMode('climate');unique();
  assert.equal(oldLabels.isConnected,false);assert.equal(oldEnergy.isConnected,false);
  for(const mode of ['energy','security','all','climate']){t.view.live.setMode(mode);unique();}
 }finally{keeper.stop();t.view.live?.stop();t.host.remove();}
 for(const selector of ['.twin-climate-labels','.twin-energy-labels','#twin-modes','#twin-mode-legend','.twin-live-labels','.twin-device-sheet'])assert.equal(document.querySelectorAll(selector).length,0,selector);
 const owners=[];t.view.scene.traverse(o=>{if(o.userData.twinMode)owners.push(o);});assert.equal(owners.length,0);
});
let failed=0; for(const [n,f] of checks)try{await f();console.log('  ok '+n);}catch(e){failed++;console.log('  FAIL '+n+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} energy mode checks passed`);process.exit(failed?1:0);
"""
if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from services import twin_plan, twin_model_bridge
    fixture = Path(__file__).parent / 'fixtures/twin_model/household-2026-11-09.json'
    plan = twin_model_bridge.flatten(twin_model_bridge.assemble(twin_plan.normalize(json.loads(fixture.read_text(encoding='utf-8')))[0])[0])
    sys.exit(run(DRIVER, {'harness_plan': plan}))
