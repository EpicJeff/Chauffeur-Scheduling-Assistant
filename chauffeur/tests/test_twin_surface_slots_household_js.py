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
        expected = [{'tier': 'low', 'geometry': '184ef725d2464417baca1c367a0bc6068239ae4997420bec0a76b36dae9ed829', 'materials': 'c162c8f191543da51e92072e571eae47cc03ab692dcab86e982e2f35740807e5', 'instances': 41, 'draws': 121, 'atlas': 'fa3877ca089f25a995d8b354eeafd0ae3761c71b322ba1e98f6e5a27a508e529', 'atlasKey': 'ca33737e8f43ce2a9b6b8378e1b45356'}, {'tier': 'high', 'geometry': 'e8860eef3846cfd2f30de466437eddaf94c3298d893d79749f231c898687ad54', 'materials': 'aae1cf5346b5c2f5aa578b7ae05cbd1841031589173ca6c89fac36080cb61b93', 'instances': 45, 'draws': 159, 'atlas': '2cce4c00a7a0dec03ee3f99de6da86ad33a75923505b3ed9f885c3d9ab55414b', 'atlasKey': 'ca33737e8f43ce2a9b6b8378e1b45356'}]
        assert got == expected, 'household geometry/material/batch/atlas differs from main'
