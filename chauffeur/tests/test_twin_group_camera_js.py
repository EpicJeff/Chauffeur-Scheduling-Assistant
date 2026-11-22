"""Group gizmo camera redraws must reuse records and rendered selection bounds."""
import json
from pathlib import Path
import sys

from test_twin_selection_js import DRIVER as SELECTION_DRIVER
from twin_editor_dom import run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Count real selectionBoxes executions while leaving its implementation intact.
DRIVER = SELECTION_DRIVER.split("await test('real_household_yard_marquee_bounds_grass_ghosts_exclusions_and_cache'")[0]
DRIVER = DRIVER.replace('return { plan, dom, view, canvas, tools,',
                        'return { setPlan: next => { plan = next; }, plan, dom, view, canvas, tools,')
DRIVER = DRIVER.replace(
    "return url.startsWith('file:') && url.endsWith('.js') ?",
    """if (url.endsWith('/editor/selection_bounds.js')) {
    const result = next(url, {...ctx, format:'module'});
    const source = String(result.source).replace('export function selectionBoxes(', 'function countedSelectionBoxes(');
    return {...result, format:'module', source:source + `\nexport function selectionBoxes(...args) { globalThis.__boundsWalks=(globalThis.__boundsWalks||0)+1; return countedSelectionBoxes(...args); }`};
  }
  return url.startsWith('file:') && url.endsWith('.js') ?""")
DRIVER += r"""
await test('group_camera_redraw_reuses_bounds_and_records', async()=>{
  const plan=makeHousehold(), seed=plan.site.planting[0];
  plan.site.planting=Array.from({length:200},(_,i)=>({...structuredClone(seed),id:`camera:${i}`,at:[(i%20)*3,Math.floor(i/20)*3]}));
  const ed=await mountEditor(plan);
  try {
    const refs=plan.site.planting.map(p=>({kind:'planting',pieceId:p.id}));
    let requests=0;
    const original=ed.view.selectionWorldBounds;
    ed.view.selectionWorldBounds=()=>{requests++;return original();};
    ed.tools.selectionStore.set(refs);
    ed.tools.setTool('select');
    const changes=()=>{for(let i=0;i<60;i++)ed.view.controls.dispatchEvent({type:'change'});};
    requests=0;globalThis.__boundsWalks=0;changes();
    const select={requests,walks:globalThis.__boundsWalks};
    requests=0;globalThis.__boundsWalks=0;
    ed.tools.setTool('move');changes();
    const move={requests,walks:globalThis.__boundsWalks};
    console.log('CAMERA_BOUNDS '+JSON.stringify({select,move}));
    if(!input.measureOnly){
      assert.deepEqual(select,{requests:0,walks:0},'Select camera events never resolve group bounds');
      assert.ok(move.requests<=1,`Move resolved group ${move.requests} times`);
      assert.ok(move.walks<=1,`Move walked bounds ${move.walks} times`);
      globalThis.__boundsWalks=0;original();original();
      assert.equal(globalThis.__boundsWalks,0,'world bounds use the existing rendered bounds cache');
      requests=0;globalThis.__boundsWalks=0;changes();
      assert.equal(requests,0,'unchanged plan/members/tool reuse the group record');
      assert.equal(globalThis.__boundsWalks,0,'camera navigation reuses rendered bounds');
      ed.tools.selectionStore.set(refs.slice(0,-1));
      assert.equal(requests,1,'member changes rebuild the group record once');
      changes();assert.equal(requests,1);
      ed.tools.setTool('rotate');changes();
      assert.equal(requests,2,'tool changes rebuild the group record once');
      ed.tools.setTool('move');changes();assert.equal(requests,3);
      ed.setPlan(structuredClone(plan));changes();
      assert.equal(requests,4,'a new plan identity rebuilds the group record once');
      changes();assert.equal(requests,4);
    }
  }finally{ed.dispose();}
});
finish();
"""

if __name__ == '__main__':
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf8'))
    kit['manifest'] = {}
    code, output = run_node(DRIVER, {
        'root': ROOT.as_posix(), 'flat': flat, 'kit': kit,
        'objectSchema': json.loads((ROOT / 'static/twin/object_schema.json').read_text(encoding='utf8')),
        'measureOnly': '--measure-only' in sys.argv,
    }, timeout=180)
    print(output)
    sys.exit(code or 0)
