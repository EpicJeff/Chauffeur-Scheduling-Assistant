"""World matrices are computed once a frame, not once per render pass. Mounted twin under Node (no GPU).

Owner trace 2026-11-20 (v2.499.953, live house, idle camera): three's per-render
updateMatrixWorld was 13% of every frame, because a frame renders the scene five
or more times (mirror, AO, beauty, transparent, shadow faces). twin_view's
render() now updates once and turns the scene's auto update off for its passes.

Run from chauffeur/: python tests/test_twin_frame_matrices_js.py
"""
import json
from pathlib import Path
import sys
from test_twin_yard_reuse_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const THREE=await import('three');
// The renderer double recomputes matrices on every render; three does that
// only while scene.matrixWorldAutoUpdate is on. Mimic r187 here, including
// what fooled the v2.499.954 gate: info.render.frame rises on EVERY render
// call, then the scene's onBeforeRender runs.
Renderer.prototype.render=function(scene,camera){
 this.info.render.frame=(this.info.render.frame||0)+1;
 if(scene.matrixWorldAutoUpdate)scene.updateMatrixWorld();
 scene.onBeforeRender?.(this,scene,camera);};
const {mountTwin}=await import(file('static/twin/twin_view.js'));
await test('one world-matrix pass per frame; the passes reuse it',async()=>{
 const view=await mountTwin(new Element(),{plan:structuredClone(input.plan),kit:{materials:{}},tier:'high',bake:false});
 try {
  const scene=view.scene,renderer=view.renderer3;let updates=0;
  const update=scene.updateMatrixWorld.bind(scene);scene.updateMatrixWorld=force=>{updates++;return update(force);};
  const flags=[],draw=renderer.render;renderer.render=function(s,c){if(s===scene)flags.push(s.matrixWorldAutoUpdate);return draw.call(this,s,c);};
  const mesh=new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());scene.add(mesh);mesh.position.set(3,4,5);
  view.render();
  assert.ok(flags.length>=1,'the frame rendered the scene');
  assert.ok(flags.every(f=>f===false),'no pass recomputes matrices: '+JSON.stringify(flags));
  assert.equal(updates,1,'one update for the whole frame');
  assert.equal(scene.matrixWorldAutoUpdate,true,'restored after the frame');
  assert.deepEqual(new THREE.Vector3().setFromMatrixPosition(mesh.matrixWorld).toArray(),[3,4,5],'a moved object is current in the frame');
  // The environment installers walk the scene once per twin frame, however many
  // passes render it (each pass bumps three's own frame counter).
  let walks=0;const traverse=scene.traverse.bind(scene);
  scene.traverse=cb=>{if(/prepare/.test(new Error().stack||''))walks++;return traverse(cb);};
  view.render();const perFrame=walks;
  assert.ok(perFrame>=3,'haze, cloud shadow and weather each walk once: '+perFrame);
  for(let i=0;i<4;i++)renderer.render(scene,view.camera||new THREE.PerspectiveCamera());
  assert.equal(walks,perFrame,'later passes of the same frame do not walk again');
  view.render();assert.equal(walks,2*perFrame,'the next frame walks again');
  scene.traverse=traverse;
  // A pass that throws still restores the flag.
  renderer.render=()=>{throw new Error('pass failed');};
  assert.throws(()=>view.render());assert.equal(scene.matrixWorldAutoUpdate,true,'restored after a failed pass');
 } finally {view.dispose();}
});
finish();
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_poolhouse.plan.json').read_text(encoding='utf-8'))
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan})
    print(out)
    sys.exit(code or 0)
