"""The live harness household keeps its scene, batches and atlas without overrides."""
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(os.environ.get('CHAUFFEUR_TEST_BASELINE_ROOT', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ['CHAUFFEUR_DATA_DIR'] = tempfile.mkdtemp(prefix='chauffeur_surface_household_')
from services import twin_model_bridge as bridge
from test_twin_tree_once_js import PREFIX
from twin_editor_dom import run_node

DRIVER = PREFIX + r"""
const {createHash} = await import('node:crypto');
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {buildYard} = await import(file('static/twin/twin_yard.js'));
const {buildAtlas} = await import(file('static/twin/bake/atlas.js'));
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes=a=>a ? createHash('sha256').update(new Uint8Array(a.buffer,a.byteOffset,a.byteLength)).digest('hex') : null;
for (const tier of ['low','high']) {
 const house=buildTwin(input.plan,input.kit,tier,{viewing:true});await house.ready;
 const yard=await buildYard(input.plan,input.kit,tier,{viewing:true});house.root.add(yard.group);
 house.root.updateMatrixWorld(true);
 const geometry=[], materials=[], unique=new Set();let draws=0;
 house.root.traverseVisible(o=>{
  if(!o.isMesh||o.layers.isEnabled(31))return;
  const mats=Array.isArray(o.material)?o.material:[o.material];mats.forEach(m=>unique.add(m.uuid));
  draws+=Array.isArray(o.material)?o.geometry.groups.filter(g=>o.material[g.materialIndex]?.visible).length:Number(o.material.visible);
  geometry.push([Object.fromEntries(Object.entries(o.geometry.attributes).map(([k,a])=>[k,bytes(a.array)])),
    bytes(o.geometry.index?.array),o.geometry.groups,o.matrixWorld.elements,bytes(o.instanceMatrix?.array)]);
  materials.push(mats.map(m=>[m.name,m.userData.materialKey??null,m.color?.getHex(),m.transparent,m.opacity,m.side,m.depthWrite]));
 });
 const atlas=buildAtlas(house.root,input.plan,{room:{density:1,page:1024,gutter:2}});
 const layout={key:atlas.key,pages:atlas.room.pages,rooms:atlas.room.rooms,
   charts:atlas.room.charts.map(c=>({id:c.id,key:c.key,page:c.page,rect:c.rect,room:c.room,density:c.density,faces:c.faces}))};
 console.log(JSON.stringify({tier,geometry:hash(geometry),materials:hash(materials),instances:unique.size,draws,atlas:hash(layout),atlasKey:atlas.key}));
}
"""


def census():
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    plan = bridge.flatten(bridge.assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit}, timeout=300)
    assert code == 0, output
    return [json.loads(line) for line in output.splitlines() if line.startswith('{"tier"')]


if __name__ == '__main__':
    got = census()
    print(json.dumps(got, indent=2))
    if '--census' not in sys.argv:
        # Updated for v2.499.949 (weatherOpen vertex attr, 029da6d5), v2.499.953 (28621a71: high lawn split into
        # 24 culled tile InstancedMeshes -> +23 draws and +23 duplicate 'yard blades' per-mesh entries in `materials`;
        # collapsing those 24 entries back to 1 yields the exact pre-28621a71 SHA-256 aae1cf53...), and v2.499.964
        # (reach-atlas-12 4/ft outdoor bake density, ff4d70a7). Material instance counts (41/45) and low draws (121) unchanged.
        expected = [{'tier': 'low', 'geometry': '6a31aca5eb39eae83b1c17848d66bc2757d2c20c3a50e41e1cc6b89d8b7f247e', 'materials': 'c162c8f191543da51e92072e571eae47cc03ab692dcab86e982e2f35740807e5', 'instances': 41, 'draws': 121, 'atlas': '6b9fa710b152a9a5e3ffb031b4255636527963216fbf4ead94e5a2d47c397f3b', 'atlasKey': '338dbe846d1552fe5b2440cab4edcac6'}, {'tier': 'high', 'geometry': 'dea8dff346fc0786def394d72841d47512c6b648becd2bec9f6f0f8e369ebaf4', 'materials': '450ceadb54c14262070e0d605bc073f5889953875b09423a3fe8c01c49a8d667', 'instances': 45, 'draws': 182, 'atlas': 'bd44d9539fbe17f0c2b5cb5a3c05a4d05af981ec023eac92a510334bc22115d6', 'atlasKey': '338dbe846d1552fe5b2440cab4edcac6'}]
        assert got == expected, 'household geometry/material/batch/atlas differs from main'
