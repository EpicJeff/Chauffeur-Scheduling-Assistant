"""HA weather fallbacks are pure and offline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tests'))
from twin_editor_dom import PRELUDE, run_node

DRIVER = PRELUDE + r"""
const {overcastFactor, weatherState} = await import(file('static/twin/sky/overcast.js'));
await test('standard HA condition table and missing or stale data',()=>{
  for(const [state,value] of Object.entries({sunny:0,'clear-night':0,partlycloudy:.4,cloudy:.85,fog:.9,rainy:1,pouring:1,snowy:1,'snowy-rainy':1,lightning:1,'lightning-rainy':1,hail:1,exceptional:1,windy:.3,'windy-variant':.3,unknown:0,unavailable:0,other:0})) assert.equal(overcastFactor({state}),value,state);
  assert.equal(overcastFactor(null),0);assert.equal(overcastFactor({}),0);
  assert.equal(overcastFactor({state:'cloudy',stale:true}),0);
  for(const [coverage,value] of [[0,0],[25,.25],[100,1],[-5,0],[120,1]]) assert.equal(overcastFactor({state:'rainy',attributes:{cloud_coverage:coverage}}),value);
  for(const coverage of [null,'',NaN,Infinity,'bad']) assert.equal(overcastFactor({state:'cloudy',attributes:{cloud_coverage:coverage}}),.85);
  assert.equal(overcastFactor({state:'unavailable',attributes:{cloud_coverage:100}}),0);
});
await test('glance entity wins, else friendly-name order, stale or missing stays clear',()=>{
  const states={'weather.z':{state:'sunny',attributes:{friendly_name:'Alpha'}},'weather.a':{state:'cloudy',attributes:{friendly_name:'Zulu'}},'sensor.a':{state:'rainy'}};
  assert.equal(weatherState(states),states['weather.z']);assert.equal(weatherState(states,'weather.a'),states['weather.a']);
  assert.equal(weatherState(states,'weather.missing'),null);assert.equal(weatherState(states,null,true),null);
  assert.equal(weatherState(null),null);
});
finish();
"""

if __name__ == '__main__':
    code, out = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(out)
    sys.exit(code or 0)
