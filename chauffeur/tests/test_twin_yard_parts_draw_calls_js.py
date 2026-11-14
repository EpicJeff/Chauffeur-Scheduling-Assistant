"""CPU draw-submission census of the harness household, with real trees/geometry.

No browser/GPU claim: count the submissions of visible meshes (material groups
count separately), matching the yard's ordinary single-pass materials.
"""
import json
from pathlib import Path
import sys
from test_twin_tree_once_js import PREFIX
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PREFIX + r"""
const {buildYard} = await import(file('static/twin/twin_yard.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const calls=root=>{let n=0;root.traverseVisible(o=>{if(o.isMesh&&!o.layers.isEnabled(31))n+=Array.isArray(o.material)?o.geometry.groups.filter(g=>o.material[g.materialIndex]?.visible).length:Number(o.material.visible);});return n;};
for(const viewing of [false,true]) {
 const house=buildTwin(input.plan,input.kit,'high',{viewing});await house.ready;
 const yard=await buildYard(input.plan,input.kit,'high',{viewing});
 const count=calls(yard.group),structure=calls(house.root);
 console.log(JSON.stringify({viewing,yard:count,structure,total:count+structure}));
 if(input.expected)assert.ok(count<=input.expected[String(viewing)]+15,`part batching adds at most 15 calls (${count})`);
}
"""

if __name__ == '__main__':
    plan = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, out = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit}, timeout=300)
    print(out)
    sys.exit(code or 0)
