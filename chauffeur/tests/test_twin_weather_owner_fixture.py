"""Execute the owner water locator against real batched pool/spa materials, no GL/browser."""
import ast
import json
from pathlib import Path
import sys

from test_twin_tree_once_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
tree = ast.parse(Path(__file__).with_name('test_twin_weather_owner_live.py').read_text(encoding='utf-8'))
water_js = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'WATER_JS' for t in n.targets))
DRIVER = PREFIX + r"""
const THREE=await import('three');
const {buildYard}=await import(file('static/twin/twin_yard.js'));
const {installWeatherSurface}=await import(file('static/twin/sky/weather_surface.js'));
await test('owner locator reads packed rain from actual rendered batched pool and spa materials',async()=>{
 const plan=input.plan,pool=plan.site.pool;
 const [x,y]=pool.polygon[0];pool.features=[{id:'owner-spa',kind:'spa',polygon:[[x+2,y+2],[x+7,y+2],[x+7,y+7],[x+2,y+7]],depth:3,raise:1}];
 const {group}=await buildYard(plan,{materials:{}},'high',{viewing:true}),scene=new THREE.Scene();scene.add(group);
 const layer=installWeatherSurface(scene);layer.prepare();layer.update({precip:'rain',rate:1,wetness:1,puddles:1},2);
 const props=new Map(),gl={getUniformLocation:(program,name)=>name==='weatherSurface'?program.shader.uniforms[name]:null,
  getUniform:(program,location)=>location.value.toArray()};
 let actual=0,missingOldTag=0;
 scene.traverse(o=>{if(!o.isMesh)return;for(const m of [].concat(o.material||[])){
  if(!m.userData.waterSurface)continue;
  actual++;if(o.userData.part!=='water')missingOldTag++;
  const shader={uniforms:{},vertexShader:THREE.ShaderLib.physical.vertexShader,fragmentShader:THREE.ShaderLib.physical.fragmentShader};m.onBeforeCompile(shader,{});
  assert.equal(shader.uniforms.weatherSurface,layer.uniforms.weatherSurface);
  props.set(m,{currentProgram:{program:{shader}}});
 }});
 assert.ok(actual>0&&missingOldTag===actual,'real pool/spa share batched materials without the original object tags');
 const renderer={properties:{get:m=>props.get(m)||{}},getContext:()=>gl};window.__twin={scene,renderer3:renderer};
 const locator=OWNER_WATER,rows=locator();
 assert.equal(rows.length,actual);assert.ok(rows.every(r=>r.water&&r.packed&&Math.floor(r.packed[3])===255));
 assert.ok(rows.some(r=>r.pieces.includes('owner-spa'))&&rows.some(r=>r.pieces.includes(pool.id||'pool:0')),'pool and spa render ranges are exercised');
 const rendered=[];scene.traverse(o=>{if(o.isMesh&&o.material?.userData.waterSurface)rendered.push(o);});
 for(const o of rendered)o.visible=false;assert.deepEqual(locator(),[],'invisible materials cannot satisfy the rendered-water assertion');
 for(const o of rendered)o.visible=true;
 layer.update({precip:'none',rate:0},3);
 assert.ok(locator().every(r=>Math.floor(r.packed[3])===0),'dry packed state is observable, never substituted by test defaults');
 props.clear();assert.ok(locator().every(r=>r.packed===null),'uncompiled materials cannot satisfy the pouring assertion');
 layer.dispose();group.userData.releasePlants?.();
});finish();
""".replace('OWNER_WATER', '(' + water_js + ')')

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan}, timeout=180)
    print(output)
    sys.exit(code or 0)
