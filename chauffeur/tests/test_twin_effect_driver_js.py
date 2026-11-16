"""Execute the production effect driver in Node without a browser or Three.js."""
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
registerHooks({load(url,ctx,next){return url.endsWith('.js')
  ? {...next(url,{...ctx,format:'module'}),format:'module'} : next(url,ctx);}});
const {effectTarget,createEffectDriver,EFFECT_TYPES}=await import(pathToFileURL(process.argv[2]).href);
const checks=[],test=(name,fn)=>checks.push([name,fn]);
const close=(a,b)=>assert.ok(Math.abs(a-b)<1e-10,`${a} != ${b}`);
const fixture={type:'fountain',sensor:'sensor.rpm',sensor_min:1000,sensor_max:3450};
const states=(value,switchState='on')=>({'sensor.rpm':{state:value},'switch.pump':{state:switchState}});
test('normalisation_example_is_exact',()=>{
  const out=effectTarget(fixture,states('2225'));assert.equal(out.t,.5);assert.equal(out.size,3.5);assert.equal(out.active,true);
});
test('clamps_and_inverted_range',()=>{
  assert.equal(effectTarget(fixture,states(0)).t,0);assert.equal(effectTarget(fixture,states(5000)).t,1);
  const inverse={...fixture,sensor_min:3450,sensor_max:1000};
  assert.equal(effectTarget(inverse,states(2225)).t,.5);assert.equal(effectTarget(inverse,states(3450)).active,false);
  assert.equal(effectTarget(inverse,states(1000)).active,true);assert.equal(effectTarget(inverse,states(5000)).t,0);
});
test('non_numeric_sensor_uses_strength_but_sensor_only_is_inactive',()=>{
  for(const value of ['unavailable','unknown','text','', '   ',null,true,false,Infinity,'Infinity',NaN]){
    const out=effectTarget({...fixture,strength:.3},states(value));assert.equal(out.t,.3);assert.equal(out.active,false);
    assert.equal(effectTarget({...fixture,entity:'switch.pump',strength:.3},states(value)).active,true);
  }
  assert.equal(effectTarget(fixture,states(' 2225 ')).t,.5);
});
test('switch_controls_activity_exactly',()=>{
  const f={...fixture,entity:'switch.pump'};
  for(const value of ['off','unavailable','unknown','ON','true',true,1])assert.equal(effectTarget(f,states(2225,value)).active,false);
  assert.equal(effectTarget(f,{'sensor.rpm':{state:2225}}).active,false);
  assert.equal(effectTarget(f,states(1000)).active,true);
  assert.equal(effectTarget(f,states(2225),true).active,false);
  for(const changes of [{stale:true},{reachable:false}]){
    const s=states(2225);Object.assign(s['switch.pump'],changes);assert.equal(effectTarget(f,s).active,false);
  }
});
test('sensor_only_requires_a_current_value_above_the_normalised_minimum',()=>{
  assert.equal(effectTarget(fixture,states(1000)).active,false);assert.equal(effectTarget(fixture,states(1001)).active,true);
  assert.equal(effectTarget(fixture,{}).active,false);assert.equal(effectTarget(fixture,states(2225),true).active,false);
  for(const changes of [{stale:true},{reachable:false}]){
    const s=states(2225);Object.assign(s['sensor.rpm'],changes);assert.equal(effectTarget(fixture,s).active,false);
    assert.equal(effectTarget({...fixture,entity:'switch.pump',strength:.2},s).t,.2);
  }
});
test('neither_link_is_always_active_with_strength_and_type_defaults',()=>{
  for(const [type,metadata]of Object.entries(EFFECT_TYPES)){
    const out=effectTarget({type,strength:.25},{},true);assert.equal(out.active,true);assert.equal(out.t,.25);
    assert.equal(out.size,metadata.size_min+.25*(metadata.size_max-metadata.size_min));
  }
  assert.equal(effectTarget({type:'fire'}).t,1);assert.equal(effectTarget({type:'fire',strength:-5}).t,0);
  assert.equal(effectTarget({type:'fire',strength:5}).t,1);
  assert.equal(effectTarget({type:'fire',strength:.5,size_min:7,size_max:1}).size,4);
});
test('initial_pose_is_direct_then_sensor_eases_for_one_second',()=>{
  const driver=createEffectDriver(fixture);assert.equal(driver.update(states(1000),false,10).t,0);
  assert.equal(driver.update(states(3450),false,11).t,0);
  let previous=0;
  for(const at of [11.01,11.1,11.25,11.5,11.75,11.99,12]){
    const out=driver.update(states(3450),false,at);assert.ok(out.t>=previous);previous=out.t;
    close(out.size,1+out.t*5);if(at===11.5)assert.equal(out.t,.5);
  }
  assert.equal(previous,1);assert.equal(driver.update(states(3450),false,14).t,1);
});
test('switch_ramps_both_directions_and_preserves_target_activity',()=>{
  const driver=createEffectDriver({...fixture,entity:'switch.pump'});
  assert.equal(driver.update(states(2225,'off'),false,0).opacity,0);
  assert.equal(driver.update(states(2225),false,1).active,true);
  assert.equal(driver.update(states(2225),false,1.5).opacity,.5);
  assert.equal(driver.update(states(2225),false,2).opacity,1);
  const start=driver.update(states(2225,'off'),false,3);assert.equal(start.active,false);assert.equal(start.opacity,1);
  assert.equal(driver.update(states(2225,'off'),false,3.5).opacity,.5);
  assert.equal(driver.update(states(2225,'off'),false,4).opacity,0);
});
test('retargeting_and_frame_rate_do_not_discontinue_pose',()=>{
  const a=createEffectDriver(fixture),b=createEffectDriver(fixture);
  for(const driver of [a,b]){driver.update(states(1000),false,0);driver.update(states(3450),false,1);}
  for(let at=1;at<1.5;at+=.03)a.update(states(3450),false,at);
  assert.deepEqual(a.update(states(3450),false,1.5),b.update(states(3450),false,1.5));
  assert.equal(a.update(states(1000),false,1.5).t,.5);
  close(a.update(states(1000),false,2).t,.25);assert.equal(a.update(states(1000),false,2.5).t,0);
});
test('low_tier_jumps_size_and_activity',()=>{
  const driver=createEffectDriver({...fixture,entity:'switch.pump'},{low:true});
  driver.update(states(1000,'off'),false,0);
  const on=driver.update(states(3450),false,.01);assert.equal(on.t,1);assert.equal(on.size,6);assert.equal(on.opacity,1);
  const off=driver.update(states(2225,'off'),false,.02);assert.equal(off.t,.5);assert.equal(off.opacity,0);
});
let passed=0;
for(const [name,fn]of checks)try{fn();passed++;console.log('  ok   '+name);}catch(e){console.log('  FAIL '+name+' '+e.stack);}
console.log(`${passed}/${checks.length} passed`);process.exit(passed===checks.length?0:1);
"""


def run():
    node = shutil.which('node')
    assert node, 'Node is required'
    scratch = ROOT / '.tmp-effects'
    scratch.mkdir(exist_ok=True)
    script = scratch / ('effect-driver-' + uuid.uuid4().hex + '.mjs')
    try:
        script.write_text(DRIVER, encoding='utf-8')
        result = subprocess.run([node, str(script), str(ROOT / 'static/twin/effects/driver.js')],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, end='')
        return result.returncode
    finally:
        script.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(run())
