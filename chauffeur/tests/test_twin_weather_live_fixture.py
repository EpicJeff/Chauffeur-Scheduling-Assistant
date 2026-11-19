"""Execute the weather live fixture and census without importing a browser harness."""
import ast
import copy
from pathlib import Path
import sys
import subprocess
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import twin_weather_state as ground

source = Path(__file__).with_name('test_twin_weather_live.py').read_text(encoding='utf-8')
tree = ast.parse(source)
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('weather', 'open_weather')
         or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'WEATHER' for t in n.targets)]
records = {}
fake = SimpleNamespace(states={})
storage = SimpleNamespace(get_settings=lambda: {}, set_app_state=lambda key, value: records.update({key: value}))


def observation(rows, settings, now):
    # Use the real service's normalization; stub only the optional site lookup.
    with patch.object(ground.twin_site, 'site', return_value={}):
        return ground.observation(rows, settings, now)


services = ModuleType('services')
services.storage = storage
services.twin_weather_state = SimpleNamespace(_lock=threading.RLock(), KEY=ground.KEY, observation=observation)
calls = []
scope = {'L': SimpleNamespace(FAKE=fake, open_twin=lambda *args, **kwargs: calls.append(kwargs)),
         'time': time, 'TIMEOUT': 40000, 'wait_weather': lambda *args: None,
         'horizon_look': lambda *args: None,
         'check': lambda value, detail: value or (_ for _ in ()).throw(AssertionError(detail))}
exec(compile(ast.Module(body=nodes, type_ignores=[]), '<weather live fixture>', 'exec'), scope)
with patch.dict(sys.modules, {'services': services}):
    for kind in scope['WEATHER']:
        scope['weather'](kind)
        record = copy.deepcopy(records[ground.KEY])
        expected_wet = kind in ('rainy', 'pouring', 'lightning-rainy')
        assert record['wetness'] == int(expected_wet), (kind, record)
        assert record['snow_cm'] == (8 if kind in ('snowy', 'fog') else 0), (kind, record)
        assert ground.puddles(record, record['updated']) == int(expected_wet)
        later = ground.advance(record, record['forcing'], record['updated'] + 30)
        if kind in ('snowy', 'fog'):
            assert later['snow_cm'] == 8, (kind, later)
        if expected_wet:
            assert later['wetness'] == 1 and ground.puddles(later, later['updated']) == 1, (kind, later)
        print('PASS live fixture real ground integration', kind)

scripts = []
page = SimpleNamespace(set_default_timeout=lambda ms: None, set_viewport_size=lambda size: None,
                       add_init_script=scripts.append)
scope['open_weather'](page, object())
assert calls == [{'query': 'tier=high&test=1&panel=true&kiosk=true', 'live': False}], calls
assert len(scripts) == 1 and 'ms===300000?1000:ms' in scripts[0]
print('PASS live fixture uses existing polling without requiring the optional live layer')

census = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'CENSUS_JS' for t in n.targets))
wait_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'wait_weather')
wait_js = [n.args[0].value for n in ast.walk(wait_node) if isinstance(n, ast.Call)
           and isinstance(n.func, ast.Attribute) and n.func.attr == 'wait_for_function']
driver = r"""
const assert=require('node:assert/strict');
const types=['MeshStandardMaterial','MeshNormalMaterial','MeshDepthMaterial','MeshDistanceMaterial','ShaderMaterial'];
const programs=types.map((type,id)=>({id,type,fragmentShader:id,program:id}));
const gl={SAMPLER_2D:1,ACTIVE_UNIFORMS:2,LINK_STATUS:3,
 getShaderSource:()=> 'uniform vec4 weatherSurface;',
 getProgramParameter:(p,key)=>key===3?true:1,
 getActiveUniform:()=>({name:'map',size:17,type:1})};
global.window={__twin:{renderer3:{info:{programs},getContext:()=>gl}}};
const rows=(CENSUS)();
assert.equal(rows[0].lit,true);assert.equal(rows[0].auxiliary,false);
for(const i of [1,2,3]){assert.equal(rows[i].lit,false);assert.equal(rows[i].auxiliary,true);}
assert.equal(rows[4].lit,false);assert.equal(rows[4].auxiliary,false);
assert.ok(rows.every(r=>r.samplers===17),'arrays keep their full sampler count');
assert.ok(rows.every(r=>r.samplers>16),'the unchanged sampler gate still rejects these rows');
console.log('PASS census executes explicit normal/depth allowlist and retains sampler array accounting');
const want={condition:'pouring',coverage:1,precip:'rain',rate:1};
const weather={condition:'pouring',preview:null,neutral:false,clouds:{coverage:1},precip:'rain',rate:1,wetness:1,puddles:1,snow_cm:0};
const u={x:1,y:0,z:1,w:255};
window.__twin={weather,weatherSurface:{uniforms:{weatherSurface:{value:u}}}};
const state=WAIT_STATE, packed=WAIT_PACKED;
assert.equal(state(want),true);assert.equal(packed(),true);
weather.wetness=0;assert.equal(state(want),false);weather.wetness=1;
u.x=0;assert.equal(packed(),false);u.x=1;
u.z=0;assert.equal(packed(),false);
console.log('PASS browser wait predicates require wetness 1 in both view state and packed surface vector');
""".replace('CENSUS', census).replace('WAIT_STATE', '(' + wait_js[0] + ')').replace('WAIT_PACKED', '(' + wait_js[1] + ')')
subprocess.run(['node', '-'], input=driver, text=True, check=True)
