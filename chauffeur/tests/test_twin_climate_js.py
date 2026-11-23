"""Run zone policy and the mounted live mode under Node; no GPU required."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {roomClimate, climateAction, resolveClimateZones, climateThermostats, climateZone} = await import(file('static/twin/live/climate.js'));
const {climateHeat, climateCool, climateIdle} = await import(file('static/twin/palette.js'));
const checks = [], check = (name, fn) => checks.push([name, fn]);
const sensor = (state, unit='°F') => ({state:String(state),attributes:{device_class:'temperature',unit_of_measurement:unit}});
const state = (mode='heat', attributes={}) => ({state:mode,attributes:{current_temperature:68,temperature:71,...attributes}});
const room = (id, level='L1', extra={}) => ({room:id,name:id,building:'b',level,...extra});
const marker = (entity_id, own='hall', extra={}) => ({device_id:entity_id,entity_id,kind:'climate',building:'b',level:'L1',room:own,placed:true,...extra});
const base = () => ({rooms:[room('hall','L1',{area_id:'a'}),room('office'),room('garage'),room('bed','L2'),room('ghost','L1',{state:'ghost'}),room('pool','L1',{building:'p'}),room('yard',null,{building:null,yard:true})],
  markers:[marker('climate.z')],devices:[{entity_id:'climate.z',area_id:'a'},{entity_id:'sensor.office',area_id:'office'}]});
const resolve = (layout, states={'climate.z':state()}) => resolveClimateZones(layout,states);
const get = (rows,id,building='b') => rows.get(`${building}:${id}`);
check('action honours every reported value before inferring', () => {
  for (const [hvac_action,action] of [['heating','heat'],['preheating','heat'],['cooling','cool'],['idle','idle'],['fan','idle'],['drying','idle'],['defrosting','idle'],['off','idle'],['other','idle']])
    assert.equal(climateAction(state('heat',{hvac_action})),action,hvac_action);
  assert.equal(climateAction(state('off',{hvac_action:'heating'})),'off');
  for(const mode of ['unknown','unavailable'])assert.equal(climateAction(state(mode)),'none');
  assert.equal(climateAction(null),'none');assert.equal(climateAction(state(),true),'none');assert.equal(climateAction({...state(),stale:true}),'none');
});
check('action inference covers modes boundaries missing and invalid readings', () => {
  for(const [mode,attrs,expected] of [
    ['heat',{},'heat'],['heat',{current_temperature:71},'idle'],['heat',{current_temperature:80},'idle'],
    ['cool',{},'idle'],['cool',{current_temperature:80},'cool'],['cool',{current_temperature:71},'idle'],
    ...['auto','heat_cool'].flatMap(mode=>[[mode,{target_temp_low:69,target_temp_high:75},'heat'],[mode,{current_temperature:80,target_temp_low:69,target_temp_high:75},'cool'],[mode,{current_temperature:72,target_temp_low:69,target_temp_high:75},'idle'],[mode,{current_temperature:69,target_temp_low:69,target_temp_high:75},'idle']]),
    ['heat',{current_temperature:null},'idle'],['cool',{temperature:'oops'},'idle'],['auto',{},'idle'],['dry',{},'idle'],['fan_only',{},'idle']])
    assert.equal(climateAction(state(mode,attrs)),expected,JSON.stringify([mode,attrs]));
});
check('whole house default stays in building and excludes ghosts and yard', () => {
  const layout=base(),rows=resolve(layout);
  assert.deepEqual([...rows.keys()],['b:hall','b:office','b:garage','b:bed']);
  assert.equal(get(rows,'office').action,'heat');assert.equal(get(rows,'hall').label,'hall 68° → 71° Heating');
  assert.equal(get(rows,'office').label,'');assert.equal(layout.climate_zones,undefined,'defaults are not stored');
  assert.deepEqual(climateHeat,[240,120,40]);assert.deepEqual(climateCool,[65,143,232]);assert.deepEqual(climateIdle,[145,153,151]);
});
check('multiple placed thermostats default to their floors and own-room tie wins', () => {
  const layout=base();layout.markers.push(marker('climate.a','bed',{level:'L2'}));
  const rows=resolve(layout,{'climate.z':state(),'climate.a':state('cool',{hvac_action:'cooling'})});
  assert.equal(get(rows,'office').entity,'climate.z');assert.equal(get(rows,'bed').entity,'climate.a');
  layout.markers[1]=marker('climate.a','office');
  assert.equal(get(resolve(layout),'office').entity,'climate.a');assert.equal(get(resolve(layout),'hall').entity,'climate.z');
  assert.equal(get(resolve(layout),'garage').entity,'climate.a');
  layout.markers.reverse();assert.equal(get(resolve(layout),'garage').entity,'climate.a','entity order is stable');
});
check('scopes precedence exceptions removed ids and explicit rooms including yard', () => {
  const layout=base();layout.markers.push(marker('climate.a','office'),marker('climate.x','bed',{level:'L2'}));
  layout.climate_zones={'climate.z':{scope:'house',rooms:[],except:['garage']},'climate.a':{scope:'floor',rooms:[],except:['hall']},'climate.x':{scope:'rooms',rooms:['office','yard','removed'],except:['bed']}};
  const rows=resolve(layout);
  assert.equal(get(rows,'hall').entity,'climate.z');assert.equal(get(rows,'office').entity,'climate.x');
  assert.equal(get(rows,'bed').entity,'climate.x','own room is implicit');assert.equal(get(rows,'yard',null).entity,'climate.x');
  assert.equal(get(rows,'garage').entity,'climate.a','Except only removes that thermostat claim');
  assert.equal(get(rows,'ghost'),undefined);assert.equal(get(rows,'removed'),undefined);assert.equal(get(rows,'pool','p'),undefined);
});
check('floor scope excludes other levels and buildings and applies Except to own room', () => {
  const layout=base();layout.climate_zones={'climate.z':{scope:'floor',rooms:['bed'],except:['hall','garage']}};
  assert.deepEqual([...resolve(layout).keys()],['b:office']);
  layout.climate_zones['climate.z']={scope:'house',except:['garage']};assert.equal(get(resolve(layout),'garage'),undefined);
});
check('unplaced default keeps HA area fallback and labels first served room', () => {
  const layout=base();layout.markers[0].placed=false;layout.rooms[1].area_id='a';
  assert.deepEqual([...resolve(layout).keys()],['b:hall','b:office']);
  assert.equal(get(resolve(layout),'hall').label,'hall 68° → 71° Heating');
  assert.equal(climateZone(climateThermostats(layout)[0],climateThermostats(layout)).scope,'rooms');
  layout.climate_zones={'climate.z':{scope:'rooms',rooms:['bed'],except:[]}};
  assert.equal(get(resolve(layout),'bed').label,'bed 68° → 71° Heating');
});
check('labels retain temperatures while colours describe action and sensors label only served rooms', () => {
  const layout=base();layout.rooms[1].area_id='office';
  const states={'climate.z':state('cool',{current_temperature:80,hvac_action:'cooling'}),'sensor.office':sensor(66)};
  const rows=resolve(layout,states);assert.equal(get(rows,'hall').label,'hall 80° → 71° Cooling');assert.equal(get(rows,'office').label,'office 66°');
  states['climate.z']=state('auto',{current_temperature:22,temperature:null,target_temp_low:20,target_temp_high:24,unit_of_measurement:'°C'});
  assert.equal(get(resolve(layout,states),'hall').label,'hall 22° → 20–24°');
  for(const mode of ['unknown','unavailable']){states['climate.z'].state=mode;assert.equal(get(resolve(layout,states),'office').label,'');}
  for(const row of resolveClimateZones(layout,states,true).values()){assert.equal(row.label,'');assert.equal(row.action,'none');}
  assert.equal(get(resolve(layout,{}),'hall').label,'');
});
check('room card thermostat reading and sensor mean unit conversion remain unchanged', () => {
  const r={area_id:'a'},devices=['climate.a','sensor.a','sensor.b'].map(entity_id=>({entity_id,area_id:'a'}));
  const states={'climate.a':state('heat',{current_temperature:80}),'sensor.a':sensor(60),'sensor.b':sensor(70)};
  assert.deepEqual(roomClimate(r,devices,states),{current:80,unit:'°F'});
  states['climate.a']=state('heat',{current_temperature:null,temperature:21,unit_of_measurement:'°C'});
  states['sensor.a']=sensor(68);states['sensor.b']=sensor(22,'°C');assert.equal(roomClimate(r,devices,states).current,21);
  delete states['climate.a'];states['sensor.a']=sensor(70);states['sensor.b']=sensor(74);assert.equal(roomClimate(r,devices,states).current,72);
  assert.equal(roomClimate(r,devices,{}).current,null);
});
check('live layout key includes zone edits and room ghost status',()=>{
  const layout=base(),before=liveModule.layoutKey(layout);
  layout.climate_zones={'climate.z':{scope:'floor',rooms:[],except:[]}};
  const saved=liveModule.layoutKey(layout);assert.notEqual(saved,before);
  layout.rooms[0].state='ghost';assert.notEqual(liveModule.layoutKey(layout),saved);
});

async function mounted(tier='medium') {
  const t=await rig({devices:[{device_id:'thermo',entity_id:'climate.k',kind:'climate',name:'Thermostat',state:'heat',attributes:{current_temperature:68,temperature:71,hvac_action:'heating'}}]});
  t.live.stop();t.view.tier=tier;
  const extra=['office','garage','plain'].map(id=>({...t.layout.rooms[0],room:id,name:id,area_id:null,lights:[]}));
  t.layout.rooms.push(...extra);t.view.plan.buildings[0].rooms.push(...extra.map((r,i)=>({id:r.room,level:'L1',polygon:[[50+i*12,0],[60+i*12,0],[60+i*12,10],[50+i*12,10]]})));
  t.layout.climate_zones={'climate.k':{scope:'house',rooms:[],except:['garage']}};
  t.view.bake={fresh:()=>{t.bakeReads=(t.bakeReads||0)+1;return [];}};
  const api=async path=>path==='api/house/live'?t.api(path):{ok:true,json:async()=>({states:structuredClone(t.states),reachable:!t.away})};
  t.live=await liveModule.mountLive(t.view,{api});
  t.floors={};t.view.scene.traverse(o=>{if(o.userData.lightWash)t.floors[o.userData.lightWash.room]=o;});return t;
}
check('mounted heat washes rooms without areas, excepted stays hidden; idle only in Climate; cleanup', async () => {
  const t=await mounted();
  try {
    t.live.setMode('climate');assert.equal(Object.keys(t.floors).length,4);
    for(const id of ['r','office','plain']){assert.equal(t.floors[id].parent.visible,true);assert.deepEqual(t.floors[id].material.color.toArray(),climateHeat.map(v=>new THREE.Color().setRGB(v/255,v/255,v/255,THREE.SRGBColorSpace).r));}
    assert.equal(t.floors.garage.parent.visible,false);
    assert.match(document.querySelector('.twin-climate-labels').textContent,/Kitchen 68° → 71° Heating/);
    assert.equal(t.live.marker('thermo').dim,false);assert.deepEqual(document.querySelectorAll('[data-mode-key="climate"] .twin-key-row').map(row=>row.textContent),['Heating','Cooling','Idle']);
    t.live.setMode('all');assert.equal(document.querySelector('.twin-climate-labels').hidden,false);assert.equal(t.floors.office.parent.visible,true);
    t.states['climate.k'].attributes.hvac_action='idle';await t.live.refresh();assert.equal(Object.values(t.floors).filter(f=>f.parent.visible).length,0,'idle adds no All draw calls');
    t.live.setMode('climate');assert.equal(t.floors.office.material.opacity,.35);assert.equal(t.floors.office.parent.visible,true);
    assert.deepEqual(t.floors.office.material.color.toArray(),new THREE.Color().setRGB(...climateIdle.map(v=>v/255),THREE.SRGBColorSpace).toArray());
    t.states['climate.k'].attributes.hvac_action='cooling';await t.live.refresh();assert.ok(t.floors.office.material.color.b>t.floors.office.material.color.r);
    t.away=true;await t.live.refresh();assert.equal(t.floors.r.parent.visible,false);assert.equal(document.querySelector('.twin-climate-labels span').hidden,true);
    t.away=false;await t.live.refresh();assert.equal(t.floors.r.parent.visible,true);
    delete t.states['climate.k'];await t.live.refresh();assert.equal(t.floors.r.parent.visible,false);assert.equal(document.querySelector('.twin-climate-labels span').hidden,true);
  } finally {t.cleanup();}
  assert.equal(document.querySelector('.twin-climate-labels'),null);const washes=[];t.view.scene.traverse(o=>{if(o.userData.lightWash)washes.push(o);});assert.equal(washes.length,0);
});
check('picked yard room has its own ground-following wash and other yards stay hidden',async()=>{
  const t=await mounted();t.live.stop();
  t.view.plan.site={yard_rooms:[{id:'garden',polygon:[[0,0],[10,0],[10,10],[0,10]]},{id:'patio',polygon:[[20,0],[30,0],[30,10],[20,10]]}],terraces:[{polygon:[[-5,-5],[15,-5],[15,15],[-5,15]],height:2}]};
  t.view.groups.site=new THREE.Group();
  t.layout.rooms.push({room:'garden',building:null,yard:true,name:'Garden',lights:[]},{room:'patio',building:null,yard:true,name:'Patio',lights:[]});
  t.layout.climate_zones={'climate.k':{scope:'rooms',rooms:['garden'],except:[]}};
  t.live=await liveModule.mountLive(t.view,{api:t.api});
  try{t.live.setMode('climate');const floors={};t.view.scene.traverse(o=>{if(o.userData.lightWash)floors[o.userData.lightWash.room]=o;});
    assert.equal(floors.garden.parent.visible,true);assert.equal(floors.patio.parent.visible,false);assert.ok(floors.garden.geometry.attributes.position.getY(0)>2);
  }finally{t.cleanup();}
});
check('pulse changes only opacity across cached frames and is steady on low or reduced motion', async () => {
  const original=performance.now.bind(performance);let now=0;Object.defineProperty(performance,'now',{configurable:true,value:()=>now});
  const media=window.matchMedia;let reduced=false;window.matchMedia=()=>({get matches(){return reduced;}});
  try {
    for(const tier of ['medium','low']) {
      const t=await mounted(tier);
      try {t.live.setMode('climate');now=750;t.live.draw();const first=t.floors.r.material.opacity,reads=t.bakeReads;
        now=2250;t.live.draw();const second=t.floors.r.material.opacity;
        assert.equal(t.bakeReads,reads,'breathing must not run the lamp/bake path');
        if(tier==='low'){assert.equal(first,.72);assert.equal(second,.72);}else{assert.equal(first,.8);assert.equal(second,.5);}
        reduced=true;t.live.draw();assert.equal(t.floors.r.material.opacity,.72);reduced=false;
      }finally{t.cleanup();}
    }
  }finally{Object.defineProperty(performance,'now',{configurable:true,value:original});window.matchMedia=media;}
});
let failed=0;
for(const [name,fn] of checks)try{await fn();console.log('  ok '+name);}catch(e){failed++;console.log('  FAIL '+name+' '+e.stack);}
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} climate checks passed`);process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
