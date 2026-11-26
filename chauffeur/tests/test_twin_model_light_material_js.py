"""Task 7 shader-hook contract in Node; GPU rendering remains Gemini's gate."""
import json, shutil, subprocess, tempfile
from pathlib import Path
from test_twin_ground_js import PREFIX, ROOT
DRIVER=PREFIX+r"""
const THREE=await import(three);
const {patchModelLighting,MODEL_LIGHT_CACHE_SUFFIX,isModelLightMaterial}=await import(file('static/twin/bake/model_light_material.js'));
for(const Type of [THREE.MeshStandardMaterial,THREE.MeshPhysicalMaterial]){
 const m=new Type();let hooks=0;m.onBeforeCompile=()=>hooks++;m.customProgramCacheKey=()=> 'upstream';
 const shared={mvBricks:{value:{}},mvLamps:{value:{}},mvSize:{value:new THREE.Vector4(10,5,5,1)}};
 assert.equal(isModelLightMaterial(m),false);
 patchModelLighting(m,shared);const key=m.customProgramCacheKey();patchModelLighting(m,shared);
 assert.equal(isModelLightMaterial(m),true);
 assert.equal(key,'upstream'+MODEL_LIGHT_CACHE_SUFFIX);assert.equal(m.customProgramCacheKey(),key);
 const shader={uniforms:{},vertexShader:'#include <project_vertex>',fragmentShader:'#include <lights_fragment_end>'};
 m.onBeforeCompile(shader,{});assert.equal(hooks,1);assert.equal(shader.uniforms.mvBricks,shared.mvBricks);
 assert.equal((shader.fragmentShader.match(/uniform highp sampler3D mvBricks;/g)||[]).length,1);
 assert.ok(shader.fragmentShader.includes('if (vMvBrick > 0.5)'));assert.deepEqual(m.defaultAttributeValues.mvBrick,[0]);
 const c=m.clone();c.onBeforeCompile=m.onBeforeCompile;c.customProgramCacheKey=m.customProgramCacheKey;
 assert.equal(isModelLightMaterial(c),false,'clone ownership is not inherited from a copied key/hook');
 patchModelLighting(c,shared);const out={uniforms:{},vertexShader:'#include <project_vertex>',fragmentShader:'#include <lights_fragment_end>'};
 c.onBeforeCompile(out,{});assert.equal((out.fragmentShader.match(/uniform highp sampler3D mvBricks;/g)||[]).length,1);assert.equal(c.customProgramCacheKey(),key);
 c.dispose();m.dispose();
}
console.log('Passed: test_model_shader_chain_idempotence_and_compile_clone_contract');
"""
def run():
 with tempfile.TemporaryDirectory(prefix='model_material_') as d:
  driver=Path(d)/'driver.mjs';job=Path(d)/'job.json'
  driver.write_text(DRIVER,encoding='utf-8');job.write_text(json.dumps({'root':ROOT.as_posix(),'kit':{},'flat':{}}),encoding='utf-8')
  r=subprocess.run([shutil.which('node'),str(driver),str(job)],capture_output=True,text=True,timeout=60)
  print(r.stdout,end='');assert not r.returncode,r.stderr
if __name__=='__main__':run()
