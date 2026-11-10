"""Task 13 drawing regressions through real JS events and household model ops."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop('HA_BASE_URL', None)
os.environ.setdefault('CHAUFFEUR_DATA_DIR', str(Path(tempfile.gettempdir()) / 'chauffeur_draw_r1'))

from services import twin_model as geometry
from services.twin_model_bridge import assemble, flatten
from services.twin_model_ops import apply

POOL = 'pool-house'
KITCHEN = 'room:5d7de10ca48340ae85c407d22337c6f7'
NORTH = 'room:a80d7712a6724446a8f023e76e90bb7c'
DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root, plan} = JSON.parse(readFileSync(process.argv[2]));
const data = s => 'data:text/javascript,' + encodeURIComponent(s);
registerHooks({resolve(s,c,n) {
  if (s === './api.js') return {url:data('export const report=e=>{globalThis.errors.push(String(e));};'),shortCircuit:true};
  if (s === '../twin_generator.js') return {url:data('export const contains=()=>true;'),shortCircuit:true};
  if (s === '../twin_hosts.js') return {url:data('export const hostPoint=()=>[0,0,0];'),shortCircuit:true};
  return n(s,c);
}, load(u,c,n) {return u.startsWith('file:') && u.endsWith('.js')
  ? {...n(u,{...c,format:'module'}),format:'module'} : n(u,c);}});
globalThis.errors=[];
const {createDraw}=await import(pathToFileURL(root+'/static/twin/editor/draw.js'));
class Element {
  constructor(){this.listeners={};this.textContent='Cancel';this.captured=false;}
  setAttribute(k,v){this[k]=v;}
  addEventListener(k,f){(this.listeners[k]??=[]).push(f);}
  emit(k,e={}){for(const f of this.listeners[k]||[])f(e);}
  setPointerCapture(){this.captured=true;}
  hasPointerCapture(){return this.captured;}
  releasePointerCapture(){this.captured=false;}
}
const nodes=new Map(), doc=new Element();
doc.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
doc.querySelector=()=>null;
globalThis.document=doc;
let prompts=0;
globalThis.window={promptInput:async()=>{++prompts;return 'Pantry';}};
const canvas=new Element(), building=plan.buildings.find(b=>b.id==='pool-house');
let current=structuredClone(building), operations=[], tool, room=null;
const view={renderer3:{domElement:canvas},controls:{enabled:true},
  screenOfFloor:(x,y)=>[x*20,y*20],floorAt:(x,y)=>[x/20,y/20]};
const tools={floor:()=>({building:current,level:current.levels.find(l=>l.id==='L1'),key:'pool-house:L1'}),
  selection:()=>({room}),setTool:t=>{tool=t;}};
const controller=new AbortController();
const draw=createDraw({view,tools,getPlan:()=>({buildings:[current]}),canEdit:()=>true,
  signal:controller.signal,panel:{message:assert.fail},gesture:work=>work(),
  op:async op=>{
    operations.push(op);
    // Even if a wall creates a room, its next click must remain available.
    if(op.op==='add_wall'||op.op==='split_room') current.rooms.push({id:'new'+operations.length,polygon:[[0,0],[1,0],[1,1]],name:'Room'});
  }});
const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
async function choose(name){doc.getElementById('rail-'+name).emit('click');await tick();}
function down(x,y){draw.pointerDown({pointerId:1,clientX:x*20,clientY:y*20});}
function up(x,y){draw.pointerUp({pointerId:1,clientX:x*20,clientY:y*20},false);}
async function click(x,y){down(x,y);up(x,y);await tick();}
await choose('draw-wall');
await click(22,12.166666666666666);await click(22,4);await click(31,4);
assert.equal(prompts,0,'wall-chain clicks never open a name prompt');
assert.equal(operations.length,2);
assert.deepEqual(operations[0].to,operations[1].from,'one exact chain corner');
draw.cancel();
await choose('draw-room');
down(2.0000002,22.3);up(14.0000002,32.0000001);await tick();
assert.deepEqual(operations.at(-1).polygon,[[2,22],[14,22],[14,32],[2,32]]);
assert.equal(prompts,0,'a new outside room does not prompt for a split name');
draw.cancel();
await choose('draw-room');
for(const p of [[0,15],[-8,15],[-8,21],[-4,21],[-4,19],[0,19],[0,15]])await click(...p);
assert.deepEqual(operations.at(-1).polygon[4],[-4,19],'a wall extension never reaches through another wall');
room=current.rooms.find(r=>r.id==='room:5d7de10ca48340ae85c407d22337c6f7').id;
await choose('split-room');await click(16,0);await click(16,17.333333333333332);
assert.equal(prompts,1,'only the explicit split prompts, once');
assert.equal(operations.at(-1).field,'name');
assert.deepEqual(globalThis.errors,[]);
controller.abort();
console.log(JSON.stringify(operations));
"""


def run():
    model, _ = assemble(json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8')))
    pool = next(b for b in model['buildings'] if b['id'] == POOL)
    before = copy.deepcopy(pool)
    out, _ = apply(model, {'op': 'draw_room', 'building': POOL, 'level': 'L1',
                           'polygon': [[2, 22], [14, 22], [14, 32], [2, 32]]})
    after = next(b for b in out['buildings'] if b['id'] == POOL)
    old = next(r for r in before['rooms'] if r['id'] == NORTH)
    neighbour = next(r for r in after['rooms'] if r['id'] == NORTH)
    assert neighbour['polygon'] == old['polygon'], (old, neighbour)
    print('  ok shared-wall drawing keeps the migrated neighbour geometry and identity')
    out, _ = apply(model, {'op': 'split_room', 'building': POOL, 'room': KITCHEN,
                           'from': [16, 0], 'to': [16, 17.333333333333332]})
    kitchen = next(r for b in out['buildings'] if b['id'] == POOL for r in b['rooms'] if r['id'] == KITCHEN)
    assert abs(geometry._area(kitchen['polygon']) - 277.3333333333333) < 1e-6, kitchen
    assert max(p[0] for p in kitchen['polygon']) == 16, kitchen
    print('  ok a concave room split gives the larger west part the original identity')
    out, _ = apply(model, {'op': 'draw_room', 'building': POOL, 'level': 'L1',
                           'polygon': [[0, 15], [-8, 15], [-8, 21], [-4, 21], [-4, 19], [0, 19]]})
    new = next(r for b in out['buildings'] if b['id'] == POOL for r in b['rooms']
               if r['id'] not in {r['id'] for r in before['rooms']})
    assert len(new['polygon']) == 6, new
    assert len(new['joints']) > 6, 'the wall cycle must retain the shared T-junction'
    print('  ok six floor corners retain every shared boundary joint for connected edits')
    if not shutil.which('node'):
        raise AssertionError('Node is required for drawing runtime proof')
    # Direct temp children avoid restricted mkdtemp permissions on Windows.
    import uuid
    stem = Path(tempfile.gettempdir()) / ('twin_draw_' + uuid.uuid4().hex)
    driver, payload = stem.with_suffix('.mjs'), stem.with_suffix('.json')
    try:
        driver.write_text(DRIVER, encoding='utf-8')
        payload.write_text(json.dumps({'root': str(ROOT).replace('\\', '/'), 'plan': flatten(model)}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(payload)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert len(json.loads(result.stdout.strip().splitlines()[-1])) == 6
        print('  ok drawing events quantize free coordinates, keep chains usable and prompt once after Split room')
    finally:
        driver.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)
    print('4/4 passed')


if __name__ == '__main__':
    run()
