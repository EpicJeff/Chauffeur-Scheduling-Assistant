"""Environment patches apply once per compile, even when another system wraps the hook.

Owner console 2026-11-19: "'weatherOpen' : redefinition" on solar_panel, paving, glass...
after the lightmap bake wrapped already-bound materials and the next frame bound them again.
"""
from pathlib import Path
import sys

from test_twin_weather_surface_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
const compileOf=material=>{
  const shader={vertexShader:THREE.ShaderLib.standard.vertexShader,fragmentShader:THREE.ShaderLib.standard.fragmentShader,uniforms:{}};
  material.onBeforeCompile(shader,null);return shader;
};
const count=(text,needle)=>text.split(needle).length-1;
await test('a hook wrapped after binding, then bound again, patches once',()=>{
  const scene=new THREE.Scene(),material=new THREE.MeshStandardMaterial({name:'paving'});
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(),material));
  const weather=installWeatherSurface(scene);weather.prepare();
  // What the lightmap bake, water and glow patches do: wrap whatever hook is there.
  const inner=material.onBeforeCompile;
  material.onBeforeCompile=function(shader,renderer){inner.call(this,shader,renderer);shader.vertexShader='attribute float lmRoom;\n'+shader.vertexShader;};
  weather.prepare();weather.prepare();
  const shader=compileOf(material);
  assert.equal(count(shader.vertexShader,'attribute float weatherOpen;'),1,'one weatherOpen declaration');
  assert.equal(count(shader.vertexShader,'attribute float lmRoom;'),1,'the wrapper still runs');
  assert.equal(count(shader.fragmentShader,'#define WEATHER_SURFACE_ACTIVE'),1,'one weather define');
  assert.ok(shader.uniforms.weatherSurface,'uniforms still bound');
  weather.dispose();
});
await test('binding twice without a wrapper stays a single patch and a stable key',()=>{
  const scene=new THREE.Scene(),material=new THREE.MeshStandardMaterial();
  scene.add(new THREE.Mesh(new THREE.BoxGeometry(),material));
  const weather=installWeatherSurface(scene);weather.prepare();const key=material.customProgramCacheKey();
  weather.prepare();assert.equal(material.customProgramCacheKey(),key);
  assert.equal(count(compileOf(material).vertexShader,'attribute float weatherOpen;'),1);
  weather.dispose();
});
finish();
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=120)
    print(output)
    sys.exit(code)
