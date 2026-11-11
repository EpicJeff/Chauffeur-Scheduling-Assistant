"""Execute Climate policy and the mounted live mode; no GPU or browser."""
import sys
from twin_live_node_rig import run

DRIVER = r"""
const {roomClimate, temperatureColor, NEUTRAL} = await import(file('static/twin/live/climate.js'));
const checks = [];
const check = (name, fn) => checks.push([name, fn]);
check('Fahrenheit colour band and extremes', () => {
  for (const v of [68,71,74]) assert.deepEqual(temperatureColor(v,[68,74]),NEUTRAL);
  const cold = temperatureColor(60,[68,74]), hot = temperatureColor(80,[68,74]);
  assert.ok(cold[2]>cold[0]); assert.ok(hot[0]>hot[2]);
  assert.deepEqual(temperatureColor(100,[68,74]),[230,88,65]);
  assert.deepEqual(temperatureColor(20,[68,74]),[65,143,232]);
});
check('Celsius colour band and extremes', () => {
  for (const v of [20,21,23]) assert.deepEqual(temperatureColor(v,[20,23],'°C'),NEUTRAL);
  assert.deepEqual(temperatureColor(15,[20,23],'°C'),[65,143,232]);
  assert.deepEqual(temperatureColor(28,[20,23],'°C'),[230,88,65]);
});
const room = {area_id:'k'}, devices = ['climate.k','sensor.a','sensor.b'].map(entity_id => ({area_id:'k',entity_id,entities:[entity_id]}));
const sensor = (state, unit='°F') => ({state:String(state),attributes:{device_class:'temperature',unit_of_measurement:unit}});
check('thermostat reading beats mean sensors and sets its band', () => {
  const value = roomClimate(room,devices,{'climate.k':{state:'heat',attributes:{current_temperature:80,temperature:72,unit_of_measurement:'°F'}},'sensor.a':sensor(60),'sensor.b':sensor(70)});
  assert.equal(value.current,80); assert.deepEqual(value.band,[71,73]); assert.equal(value.label,'80°F → 72°F');
});
check('mean of usable temperature sensors with unit conversion', () => {
  const states = {'sensor.a':sensor(68),'sensor.b':sensor(22,'°C'),'climate.k':{state:'heat',attributes:{temperature:21,unit_of_measurement:'°C'}}};
  assert.equal(roomClimate(room,devices,states).current,21);
  assert.equal(roomClimate(room,devices,states).label,'21°C → 21°C');
  assert.equal(roomClimate(room,devices,{'sensor.a':sensor(70),'sensor.b':sensor(74)}).current,72);
});
check('no reading or unavailable thermostat stays neutral and silent', () => {
  for (const states of [{},{'climate.k':{state:'unavailable',attributes:{current_temperature:80}}},{'sensor.a':sensor('unavailable')}]) {
    const value = roomClimate(room,devices,states); assert.equal(value.current,null); assert.equal(value.label,''); assert.deepEqual(value.rgb,NEUTRAL);
  }
});
check('range label and Celsius defaults', () => {
  const value = roomClimate(room,devices,{'climate.k':{state:'heat_cool',attributes:{current_temperature:22, target_temp_low:20,target_temp_high:24,unit_of_measurement:'°C'}}});
  assert.equal(value.label,'22°C → 20–24°C'); assert.deepEqual(value.band,[19,25]);
  assert.deepEqual(roomClimate(room,devices,{'sensor.a':sensor(21,'°C')}).band,[20,23]);
});
check('registered mode paints existing floor, labels and marker focus then cleans up', async () => {
  const t = await rig({devices:[
    {device_id:'thermo',name:'Thermostat',entity_id:'climate.k',kind:'climate',state:'heat',attributes:{current_temperature:80,temperature:72,unit_of_measurement:'°F'}},
    {device_id:'temp',name:'Temp',entity_id:'sensor.a',kind:'sensor',state:'70',attributes:{device_class:'temperature'}},
    {device_id:'light',name:'Light',entity_id:'light.a',kind:'light',state:'off'}]});
  try {
    const strip = document.getElementById('twin-modes');
    await press([...strip.querySelectorAll('button')].find(n=>n.textContent==='Climate'));
    assert.equal([...strip.querySelectorAll('button')].find(n=>n.textContent==='Climate').getAttribute('aria-pressed'),'true');
    const floors=[]; t.view.scene.traverse(o=>{if(o.userData.lightWash) floors.push(o);});
    assert.equal(floors.length,1); assert.ok(floors[0].parent.visible); assert.ok(floors[0].material.color.r > floors[0].material.color.b);
    assert.match(document.querySelector('.twin-climate-labels').textContent,/80°F.*72°F/);
    assert.equal(t.live.marker('thermo').dim,false); assert.equal(t.live.marker('temp').dim,false); assert.equal(t.live.marker('light').dim,true);
    assert.equal(document.getElementById('twin-mode-legend').hidden,false);
    t.states['climate.k'].attributes.current_temperature=60; await t.live.refresh();
    assert.ok(floors[0].material.color.b > floors[0].material.color.r);
    delete t.states['climate.k']; delete t.states['sensor.a']; await t.live.refresh();
    assert.equal(document.querySelector('.twin-climate-labels span').hidden,true);
    assert.equal(floors[0].parent.visible,true);
    t.live.setMode('all'); assert.equal(floors[0].parent.visible,false);
  } finally { t.cleanup(); }
  assert.equal(document.querySelector('.twin-climate-labels'),null);
});
let failed=0;
for(const [name,fn] of checks) {try{await fn(); console.log('  ok  '+name);}catch(e){failed++; console.log('  FAIL '+name+' '+e.stack);}}
assert.deepEqual(domErrors,[]); assert.deepEqual(escaped,[]);
console.log(`${checks.length-failed}/${checks.length} climate checks passed`); process.exit(failed?1:0);
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER))
