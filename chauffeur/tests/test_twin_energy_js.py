"""Mounted energy mode, geometry, warm-up and drawer paths under node."""
import json
from pathlib import Path
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {flowReading} = await import(file('static/twin/live/energy_mapping.js'));
const {energyAnchors,energyTopology,energyPlacementLegend,roofPoints,flowCurve,flowRoute,lotPoint,worldPoint} = await import(file('static/twin/live/energy_geometry.js'));
const {flowLabelPositions,mountEnergy,createRoofFade,FLOW_COLORS}=await import(file('static/twin/live/energy.js'));
const {solarPlanes,solarZones,solarLayout,solarPoint,solarCovered,solarRect}=await import(file('static/twin/twin_solar.js'));
const {mountModes} = await import(file('static/twin/live/modes.js'));
const checks=[], check=(n,f)=>checks.push([n,f]);
const d=(id,entity_id,state,attributes={},kind='sensor')=>({device_id:id,name:id,entity_id,state:String(state),attributes,kind});
const power={device_class:'power',unit_of_measurement:'W'};

const flatRoof=()=>({id:'roof',kind:'flat',rect:[-40,-10,40,20],pitch:0,plate:10,overhang:0,level:'L1'});
async function energyRig(args){
 const devices=[...args.devices];if(!devices.some(d=>d.entity_id==='sensor.house_power'))devices.push(d('panel','sensor.house_power',500,power));
 const t=await rig({...args,devices}),b=t.view.plan.buildings[0];b.walls=[];b.anchors=[];
 b.roof={sections:[flatRoof()]};b.solar_zones=[{id:'z',roof:'roof',plane:[0,0,10],rect:[-30,-5,-10,5]}];
 t.view.plan={...t.view.plan};await t.live.refresh();return t;
}
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
  await press([...document.getElementById('twin-modes').querySelectorAll('button')].find(n=>n.textContent==='Energy'));
  let s=t.live.energy();const visible=()=>Object.fromEntries(t.live.energy().ribbons.filter(r=>r.visible).map(r=>[r.id,r.watts]));
  assert.deepEqual(visible(),{'solar:house':3000,'solar:battery':2000,'solar:grid':3000,'car:0':1000});assert.ok(s.cars[0].visible);
  t.live.configureEnergy({mapping:{home_includes_chargers:false},cars:[]});
  assert.deepEqual(visible(),{'solar:house':4000,'solar:battery':2000,'solar:grid':2000,'car:0':1000});
  t.live.configureEnergy({mapping:{home_includes_chargers:true},cars:[]});
  const grid=[];t.view.scene.traverse(o=>{if(o.userData.energyRibbon==='grid:house')grid.push(o);}); const geometry=grid[0].geometry,material=grid[0].material;
  t.states['sensor.solar_power'].state='1000';t.states['sensor.battery_power'].state='2000';t.states['sensor.grid_power'].state='2500';t.states['sensor.house_power'].state='5500';
  t.states['sensor.tesla_charge_power'].state='40';t.states['device_tracker.tesla_location'].state='away';await t.live.refresh();
  s=t.live.energy();assert.deepEqual(visible(),{'solar:house':1000,'battery:house':2000,'grid:house':2500});assert.equal(s.cars[0].visible,false);
  assert.equal(grid[0].geometry,geometry);assert.equal(grid[0].material,material);assert.equal(t.live.marker('solar').dim,false);
  t.states['sensor.battery_power'].state='-2000';t.states['sensor.grid_power'].state='-2500';
  t.live.configureEnergy({mapping:{battery_positive:'charge',grid_positive:'export',cars:[]},cars:[]});await t.live.refresh();
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
  assert.ok(core.visible && halo.visible);assert.equal(halo.material.blending,THREE.AdditiveBlending);assert.equal(core.material.depthTest,false);
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
check('overlapping midpoint labels are separated',()=>{
 const placed=flowLabelPositions(Array.from({length:8},()=>({x:700,y:400,width:130})),{left:0,right:1400});
 for(let i=0;i<placed.length;i++)for(let j=0;j<i;j++){
  const a=placed[i],b=placed[j];assert.ok(!(a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top));
 }
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
check('roof-only depth fade warms, caches camera poses, and restores renderer state',()=>{
 let renders=0,warms=0,warmTargetValid=false,target=null,color=new THREE.Color('#182030'),alpha=.5;
 const renderer={autoClear:false,getRenderTarget:()=>target,setRenderTarget:t=>{target=t;},getDrawingBufferSize:v=>v.set(1400,1000),
  getClearColor:v=>v.copy(color),getClearAlpha:()=>alpha,setClearColor:(c,a)=>{color.set(c);alpha=a;},
  compileAsync:async()=>{warms++;warmTargetValid=!!target?.isWebGLRenderTarget;},render:(scene)=>{renders++;assert.equal(scene.children.length,1);assert.equal(target.width,700);assert.equal(target.height,500);}};
 const camera=new THREE.PerspectiveCamera(38,1.4,.1,1000),view={renderer3:renderer,camera,groups:{roof:{visible:true}}},fade=createRoofFade(view);
 const original=color.clone();
 try{
  fade.setPoints([new THREE.Vector3(-1,0,0),new THREE.Vector3(1,0,0),new THREE.Vector3(0,0,1)]);fade.warm();assert.equal(warms,1);assert.ok(warmTargetValid,'warm uses the same output target as the roof pass');
  fade.draw(false);assert.equal(renders,0);fade.draw(true);assert.equal(renders,1);assert.equal(target,null);assert.equal(renderer.autoClear,false);assert.equal(alpha,.5);assert.ok(color.equals(original));
  fade.draw(true);assert.equal(renders,1);camera.position.x=1;fade.draw(true);assert.equal(renders,2);
  view.groups.roof.visible=false;fade.draw(true);assert.equal(fade.uniforms.roofFadeEnabled.value,0);assert.equal(renders,2);
 }finally{fade.stop();}
});
check('warm path sees away cars and cones before entry and on time look',async()=>{
 const t=await energyRig({devices:[d('car','sensor.tesla_charge_power',1000,power),d('tracker','device_tracker.tesla_location','away'),d('camera','camera.k','idle',{},'camera')]});
 let extra;
 try{
  t.live.stop(); t.view.tier='low'; let warms=0,sawCar=false,sawCone=false;
  t.view.renderer3.compileAsync=async(scene)=>{warms++;scene.traverse(o=>{if(o.userData.energyCar)sawCar ||= o.visible;if(o.userData.cameraCone)sawCone ||= o.visible;});};
  const live={layout:()=>t.layout,peek:()=>t.states,state:id=>t.states[id],stale:()=>false,subscribe:()=>()=>{},rooms:()=>[],setMode(){}};
  extra=mountModes(t.view,live);assert.ok(warms>0);assert.ok(sawCar);assert.ok(sawCone);
  const before=warms;t.view.onTimeLook();assert.equal(warms,before+1);
  extra.setMode('energy');extra.setMode('all');extra.setMode('energy');assert.equal(warms,before+1);
 }finally{extra?.stop();t.cleanup();}
});
check('all placed-role combinations obey topology and placement legend',()=>{
 const mapping={battery_power:'sensor.battery',cars:[{name:'EV',charge_power:'sensor.ev'}]};
 for(let mask=0;mask<32;mask++){
  const a={solar:mask&1?[1,2,3]:null,battery:mask&2?[4,5,6]:null,house:mask&4?[7,8,9]:null,grid:mask&8?[10,11,12]:null,cars:[mask&16?[13,14,15]:null]};
  const rows=energyTopology(a,mapping),ids=rows.map(r=>r.id);
  for(const [source,target] of [['solar','house'],['solar','battery'],['solar','grid'],['battery','house'],['grid','house'],['grid','battery'],['battery','grid']])
   assert.equal(ids.includes(source+':'+target),!!(a[source]&&a[target]));
  assert.equal(ids.includes('car:0'),!!(a.house&&a.cars[0]));
  for(const row of rows){const [source,target]=row.id.split(':');assert.deepEqual(row.from,source==='car'?a.house:a[source]);assert.deepEqual(row.to,source==='car'?a.cars[Number(target)]:a[target]);}
  const legend=energyPlacementLegend(a,mapping);assert.equal(legend.includes('Place the meter'),!a.grid);assert.equal(legend.includes('Place the electric panel'),!a.house);assert.equal(legend.includes('Place the charger'),!a.cars[0]);
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
