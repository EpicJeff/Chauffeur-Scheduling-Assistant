"""Node regression proof for connected drag dependencies and preview work.

Uses real household geometry with CPU renderer/DOM doubles. Chromium still
owns the 33 ms GPU gate; these checks make no timing claim.
Run from chauffeur/: python tests/test_twin_drag_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DRIVER = r"""
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import {pathToFileURL} from 'node:url';
import {readFileSync} from 'node:fs';
const {root, flat, kit} = JSON.parse(readFileSync(process.argv[2]));
const file = p => pathToFileURL(root + '/' + p).href;
const data = source => 'data:text/javascript,' + encodeURIComponent(source);
const three = file('static/vendor/three-r187/three.module.js');
registerHooks({resolve(spec, ctx, next) {
  if (spec === 'three') return {url: data(`export * from '${three}'; export const WebGLRenderer = globalThis.Renderer;`), shortCircuit: true};
  if (spec === 'three/addons/controls/OrbitControls.js') return {url: data(`import {EventDispatcher,Vector3} from '${three}';
    export class OrbitControls extends EventDispatcher {
      constructor(camera){super();this.object=camera;this.target=new Vector3();this.enabled=true;}
      update(){this.object.lookAt(this.target);this.object.updateMatrixWorld();} dispose(){}
    }`), shortCircuit: true};
  if (spec.startsWith('three/addons/')) return {url: file('static/vendor/three-r187/addons/' + spec.slice(13)), shortCircuit: true};
  if (spec === './twin_yard.js') return {url: data(`import {Group} from '${three}'; export async function buildYard(){return {group:new Group()};}`), shortCircuit: true};
  return next(spec, ctx);
}, load(url, ctx, next) {
  return url.startsWith('file:') && url.endsWith('.js') ? {...next(url, {...ctx, format:'module'}), format:'module'} : next(url, ctx);
}});
class Element extends EventTarget {
  constructor(){super();this.children=[];this.style={};this.dataset={};this.clientWidth=1440;this.clientHeight=900;}
  getBoundingClientRect(){return {left:0,top:0,right:1440,bottom:900,width:1440,height:900};}
  append(...nodes){this.children.push(...nodes);for(const n of nodes)n.parentElement=this;}
  appendChild(node){this.append(node);}
  replaceChildren(){for(const n of this.children)n.parentElement=null;this.children=[];}
  remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);}
  closest(){return this;} setAttribute(k,v){this[k]=v;}
  getContext(){return {getExtension:()=>null};}
}
globalThis.window = new Element();
globalThis.document = {createElement:()=>new Element(),getElementById:()=>null};
globalThis.location = {search:'?test=1&tier=low'};
globalThis.getComputedStyle = ()=>({getPropertyValue:()=>''});
globalThis.CustomEvent = class extends Event {constructor(name,opts){super(name);this.detail=opts.detail;}};
globalThis.ResizeObserver = class {observe(){} disconnect(){}};
let renders = 0;
globalThis.Renderer = class {
  constructor(){this.domElement=new Element();this.shadowMap={};this.info={render:{calls:0,triangles:0},reset(){}};}
  setPixelRatio(){} getContext(){return {getExtension:()=>null};} setSize(){} setAnimationLoop(){}
  render(scene){renders++;scene.updateMatrixWorld(true);} dispose(){} forceContextLoss(){}
};
const {createDrag, piecesOnMovedJoints} = await import(file('static/twin/editor/drag.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createDimensions} = await import(file('static/twin/editor/dimensions.js'));
const {buildTwin} = await import(file('static/twin/twin_generator.js'));
const {disposeObject} = await import(file('static/twin/twin_library.js'));
let passed = 0;
const ok = text => {passed++; console.log('  ok ' + text);};
const deps = piecesOnMovedJoints({
  walls:[{id:'wall',joints:['a','b']},{id:'stem',joints:['b','c']},{id:'remote',joints:['d','e']}],
  rooms:[{id:'left',joints:['a','b','c']},{id:'crossing',joints:['derived','d','e']},{id:'far',joints:['d','e','f']}],
  openings:[{id:'door',wall:'wall'},{id:'remote-door',wall:'remote'}],
  anchors:[{id:'switch',host:{wall:'stem'}},{id:'roof',host:{roof:'roof'}},{id:'ground',host:{ground:true,at:[0,0]}}],
  items:[{id:'chair',host:{floor:'left'}},{id:'light',host:{ceiling:'crossing'}},{id:'far-chair',host:{floor:'far'}}],
}, ['b','derived']);
assert.deepEqual(deps,{walls:['wall','stem'],rooms:['left','crossing'],openings:['door'],anchors:['switch'],items:['chair','light']});
ok('joint dependencies include attached walls, derived room crossings and hosts, excluding remote pieces');

// Exact plan ids survive both batching modes, including persisted T splits.
for (const editableLevel of [null,'main-house:L1']) {
  const twin = buildTwin(flat, kit, 'low', {editableLevel}); await twin.ready;
  let split = 0;
  for (const b of flat.buildings) for (const wall of b.walls) {
    const key = b.id + ':' + wall.id;
    if (wall.kind === 'separator') {
      assert.equal(twin.pieceBounds.has(key),false);
      assert.equal(twin.pickObjects.has(key),false);
    } else {
      assert.ok(twin.pieceBounds.has(key), 'registered wall: ' + key);
      assert.equal(twin.pickObjects.get(key).userData.pieceId, wall.id);
      assert.ok(twin.pieces.get(key).every(o=>o.parent), 'registry holds live render objects');
      if (wall.id.includes('~')) split++;
    }
  }
  assert.ok(split > 0, 'fixture exercises R31b ids');
  disposeObject(twin.root);
}
ok('batched and focused household solid walls retain exact plan ids; separators stay absent');

const host = new Element(), view = await mountTwin(host,{plan:flat,kit,tier:'low',preserveCamera:true});
await view.setEditableLevel('main-house:L1'); view.setView('main-house:L1');
const b = flat.buildings.find(b=>b.id==='main-house'), original = JSON.stringify(flat);
const roomA = 'room:070aa0ca32b94170968a5e2cbf0fcc6f', roomB = 'room:6ae35a0dcd044566b9f9956dd1b2b4e3';
const wallId = 'wall:738a2cbddd52469a968bac0b57b29ebc', wall = b.walls.find(w=>w.id===wallId);
const sel = {kind:'wall',id:wallId,building:b.id,level:'L1',room:roomA};
view.setSelection({selected:sel,room:{kind:'room',building:b.id,level:'L1',id:roomA,walls:[wallId],allowed:[wallId,roomA]}});
const abort = new AbortController(), ops = [];
const dimensions = createDimensions({view,onCommit:op=>ops.push(op),canEdit:()=>true,signal:abort.signal});
let preview;
const drag = createDrag({view,model:()=>flat,onCommit:op=>ops.push(op),onPreview:p=>{
  preview=p;const building=p.buildings.find(b=>b.id===sel.building);
  dimensions.show({building,piece:building.walls.find(w=>w.id===wallId)});
}});
const extent = id => {const box=view.worldBox(id,b.id);return box.max[1]-box.min[1];};
const a0=extent(roomA), b0=extent(roomB), box0=view.worldBox(wallId,b.id);
const roofs=JSON.stringify(view.roofStats());
const materials=new Map(); let disposed=0;
view.scene.traverse(o=>{if(o.material) {materials.set(o,o.material); for(const m of [].concat(o.material))m.addEventListener('dispose',()=>disposed++);}
});
assert.ok(drag.begin(sel,[2.5,wall.from[1]]));
let labels;
for(let step=1;step<=12;step++) {
  const before=renders; assert.ok(drag.update([2.5,wall.from[1]-step/12]));
  assert.equal(renders-before,1,'one render submission per preview');
  assert.equal(disposed,0,'no scene-wide selection material disposal');
  for(const [o,m] of materials)assert.equal(o.material,m,'selection material identity is retained');
  const now=host.children.at(-1).children;
  if(labels)assert.deepEqual(now,labels,'dimension buttons are reused through the gesture');
  labels=[...now];
  assert.ok(drag.lastDragFrameMs>0);
}
assert.equal(labels.length,3);
assert.equal(ops.length,0); assert.equal(JSON.stringify(flat),original);
assert.equal(JSON.stringify(view.roofStats()),roofs);
const cos=Math.cos((b.rotation||0)*Math.PI/180);
assert.ok(Math.abs(extent(roomA)-a0+cos)<.02,'one adjacent floor shrinks');
assert.ok(Math.abs(extent(roomB)-b0-cos)<.02,'the other adjacent floor grows');
assert.notDeepEqual(view.worldBox(wallId,b.id),box0);
await drag.finish(); assert.equal(ops.length,1); assert.equal(ops[0].op,'move_wall');
assert.ok(Math.abs(ops[0].by[1]+1)<.02);
ok('real household buffers and both floors preview with retained materials, labels and one release op');

// The retained button must use the latest distance and operation, not the
// first preview's closure. Set the southern gap to its current value - 1 ft.
const latest = preview.buildings.find(row=>row.id===b.id);
const currentY = latest.walls.find(w=>w.id===wallId).from[1];
window.promptInput=async()=>`10'-0"`;
labels[1].dispatchEvent(new Event('click')); await new Promise(r=>setImmediate(r));
assert.equal(ops.length,2); assert.equal(ops[1].op,'move_wall');
assert.ok(Math.abs(ops[1].by[1]-(14.333333333333334+10-currentY))<.01,'button uses the current gap');
view.rebuildLevel(b.id,'L1',flat);
assert.ok(drag.begin(sel,[2.5,wall.from[1]])); drag.update([2.5,wall.from[1]-2]); await drag.finish(true);
assert.equal(ops.length,2);
const reset=view.worldBox(wallId,b.id);
assert.ok(Math.abs(reset.min[0]-box0.min[0])<.001 && Math.abs(reset.max[1]-box0.max[1])<.001);
ok('retained dimension button commits its latest value and cancellation restores geometry without an op');

const perfWall = b.walls.find(w=>w.id==='wall:27baac0e440145c2aaeab79271823cba');
const perfSelection = {kind:'wall',id:perfWall.id,building:b.id,level:'L1'};
const perfBox = view.worldBox(perfWall.id,b.id), otherBox = view.worldBox(wallId,b.id);
let touched;
const rebuildLevel = view.rebuildLevel.bind(view);
view.rebuildLevel = (building,level,plan,pieces)=>{touched=pieces;rebuildLevel(building,level,plan,pieces);};
const refused = createDrag({view,model:()=>flat,onCommit:()=>{throw new Error('refused');}});
assert.ok(refused.begin(perfSelection,[52.5,perfWall.from[1]]));
for(let step=1;step<=12;step++)refused.update([52.5,perfWall.from[1]+step/4]);
assert.ok(touched.walls.length < b.walls.filter(w=>w.level==='L1').length);
assert.ok(touched.rooms.includes('room:b3fc2ad6ea584ed3a9ac77f47983dd61'));
assert.ok(touched.rooms.includes('room:e7b4abf892a4489ba8142fe31395d15c'));
assert.deepEqual(view.worldBox(wallId,b.id),otherBox,'unconnected wall bounds stay untouched');
assert.notDeepEqual(view.worldBox(perfWall.id,b.id),perfBox);
await assert.rejects(refused.finish(),/refused/);
const rolledBack = view.worldBox(perfWall.id,b.id);
assert.ok(Math.abs(rolledBack.min[0]-perfBox.min[0])<.001 && Math.abs(rolledBack.max[1]-perfBox.max[1])<.001);
ok('P3 wall passes only its connected pieces and a refused release rolls back the preview');
abort.abort(); view.dispose();
console.log(`${passed}/${passed} passed`);
"""


def run():
    if not shutil.which('node'):
        print('SKIP node is unavailable')
        return
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths = []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root':ROOT.as_posix(),'flat':flat,'kit':kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_drag_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
