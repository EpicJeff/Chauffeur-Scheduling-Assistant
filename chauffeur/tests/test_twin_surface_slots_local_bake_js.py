"""Execute the live wall-locality observation against the real household in Node."""
import json
from pathlib import Path

import test_twin_surface_slots_live as S
from test_twin_surface_slots_sequence_js import SETUP
from services import twin_edit, twin_materials, twin_store
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = SETUP + '\nconst prepare=(' + S.BAKE_PREPARE + ');\nconst compare=(' + S.BAKE_COMPARE + ');\n' + r"""
await view.setEditableLevel(input.floor);
const before=await prepare({kit:input.kit,...input.target});
await view.rebuild(structuredClone(input.after));
const result=await compare();
console.log('LOCAL_BAKE '+JSON.stringify({before,result}));
assert.equal(result.key,before.key,'atlas namespace stays unchanged');
assert.equal(result.sameLayout,true,'every chart address stays unchanged');
assert.ok(result.changed.length,'the wall finish reaches actual charts');
assert.ok(result.changed.every(id=>result.target.includes(id)),'changed charts belong to the selected wall face');
assert.deepEqual([...result.changed].sort((a,b)=>a-b),[...result.target].sort((a,b)=>a-b),
    'every chart of this uniformly finished face changes');
assert.equal(result.invalidated,true,'material reach is invalidated');
assert.deepEqual([...result.dirty].sort(),[...result.expected].sort(),'exact reaching-light set');
assert.ok(result.dirty.length>0&&result.dirty.length<result.total,'a strict subset of household lights');
assert.ok(result.pages.length,'dirty lights own real pages');
view.dispose();console.log('PASS live wall-locality observation in mounted runtime');process.exit(0);
"""


def main():
    # Match this live scenario, which adds neither cost assets nor a pool ledge.
    assets = S._seed()
    plan = twin_store.current()
    b, w, room = S.L._target(plan)
    dx, dy = [v-u for u, v in zip(w['from'], w['to'])]
    centre = [sum(p[i] for p in room['polygon'])/len(room['polygon']) for i in (0, 1)]
    middle = [(u+v)/2 for u, v in zip(w['from'], w['to'])]
    side = 'right' if sum(n*(c-m) for n,c,m in zip([-dy, dx], centre, middle)) > 0 else 'left'
    twin_edit.save({'op': 'set_material', 'building': b['id'],
                    'target': {'wall': w['id'], 'side': side},
                    'material': {'id': assets['selected']['id']}}, S.H.PARENT['id'])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = twin_materials.page_manifest()
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'plan': plan, 'kit': kit,
                            'after': twin_store.current(), 'floor': f'{b["id"]}:{w["level"]}',
                            'target': {'bid': b['id'], 'wid': w['id'], 'side': side}}, timeout=600)
    print(output, flush=True)
    assert code == 0, output


if __name__ == '__main__':
    main()
