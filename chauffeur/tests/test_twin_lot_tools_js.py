"""CPU raycasting proof for lot handles; Chromium owns the image/input gates.

Uses the real renderer geometry with Task 11's CPU renderer and DOM doubles.
Run from chauffeur/: python tests/test_twin_lot_tools_js.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as DRAG_DRIVER

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0].replace(
    "export const WebGLRenderer = globalThis.Renderer;",
    "export const WebGLRenderer = globalThis.Renderer; export const TextureLoader = globalThis.PlotLoader;") + r"""
const THREE = await import(three);
globalThis.PlotLoader = class {
  load(url, done) { assert.match(url, /sheets\/plot\/1.png$/); queueMicrotask(() => done(new THREE.Texture())); }
};
const nodes = new Map(), shell = new Element();
const el = id => { if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id); };
Element.prototype.querySelectorAll = function(){return [];};
Element.prototype.getAttribute = function(key){return this[key];};
Element.prototype.focus = function(){};
document.getElementById = el; document.querySelector = () => shell;
document.addEventListener = () => {};
el('place-view').hidden = true;
el('rail-select').setAttribute('aria-pressed', 'true');
let scheduled;
globalThis.requestAnimationFrame = fn => {scheduled = fn; return 1;};
globalThis.cancelAnimationFrame = () => {};
window.chfBase = '/'; window.showGlobalAlert = text => {throw Error(text);};
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createLotTools, snapFootprint} = await import(file('static/twin/editor/lot_tools.js'));
const b = flat.buildings.find(b => b.id === 'pool-house'); b.rotation = 270;
const view = await mountTwin(new Element(), {plan: flat, kit, tier:'low', preserveCamera:true});
const canvas = view.renderer3.domElement;
const captures = new Set(); canvas.setPointerCapture = id => captures.add(id);
canvas.hasPointerCapture = id => captures.has(id); canvas.releasePointerCapture = id => captures.delete(id);
let selected = {kind:'building',id:b.id}, enabled = true, paused = false, answer = null, operations = [], calls = [];
const abort = new AbortController();
const outline = [...b.levels].sort((a,b)=>a.elevation-b.elevation)[0].outline;
const rot = (p,a) => {a*=Math.PI/180;return [Math.cos(a)*p[0]-Math.sin(a)*p[1],Math.sin(a)*p[0]+Math.cos(a)*p[1]];};
const at = (p,position=b.position,rotation=b.rotation) => rot(p,rotation).map((v,i)=>v+position[i]);
const boundsCentre = [0,1].map(i=>(Math.min(...outline.map(p=>p[i]))+Math.max(...outline.map(p=>p[i])))/2);
const read = {id:'r1',source:'plot',page:1,matrix:[170,0,0,-220,-30,190],
  lot:flat.site.lot,street_edge:[0,1],suggestions:[]};
const sheets = {place:{buildings:[],lot:{read}},kinds:[]};
const lot = createLotTools({view,getPlan:()=>flat,getSheets:()=>sheets,getSelection:()=>selected,
  select:item=>{selected=item ? {kind:'building',id:item.id} : {};},canEdit:()=>enabled,
  pauses:{lotPlacement:()=>paused ? {building:b.id} : null,setLotTransform:value=>{answer=value;}},
  signal:abort.signal,reload:async()=>{},op:async ops=>{
    operations.push(...ops);
    for(const op of ops) {
      if(op.op==='move_building')b.position=[...op.to];
      else {b.position=rot(b.position.map((v,i)=>v-op.about[i]),op.rotation-b.rotation).map((v,i)=>v+op.about[i]);b.rotation=op.rotation;}
    }
    await view.rebuild(flat);
  }});
const event = p => {
  view.camera.updateMatrixWorld(true);
  const q=new THREE.Vector3(p[0]*.3048,0,-p[1]*.3048).project(view.camera);
  return {clientX:(q.x+1)*720,clientY:(1-q.y)*450,button:0,pointerId:1};
};
const press = kind => {
  const h=lot.lotHandles().find(h=>h.kind===kind); assert.ok(h);
  assert.equal(lot.pointerDown({...event(h.at),clientX:h.screen[0],clientY:h.screen[1]}),true); return h;
};
const release = async p => {lot.pointerUp(event(p),false);await new Promise(r=>setImmediate(r));};
const near = (p,q,t=.001) => assert.ok(Math.hypot(...p.map((v,i)=>v-q[i]))<t, `${p} near ${q}`);
const look = () => {
  const mid=at(boundsCentre);view.camera.position.set(mid[0]*.3048,90*.3048,-(mid[1]-.01)*.3048);
  view.camera.lookAt(mid[0]*.3048,0,-mid[1]*.3048);view.camera.updateMatrixWorld(true);view.setView('ext');
};
await new Promise(r=>setImmediate(r)); look();
assert.deepEqual(lot.underlay(),{source:'plot',page:1,opacity:.6,visible:true});
const sheet=view.scene.children.find(o=>o.material?.map), vertices=sheet.geometry.attributes.position;
near([vertices.getX(0)/.3048,-vertices.getZ(0)/.3048],[-30,-30]);
near([vertices.getX(2)/.3048,-vertices.getZ(2)/.3048],[140,190]);
assert.equal(sheet.material.opacity,.6);
console.log('  ok page matrix maps full-page UV to lot feet at 0.6 opacity');

let before={position:[...b.position],rotation:b.rotation}, h=press('move');
const halfway=[h.at[0]-5,h.at[1]-3], end=[h.at[0]-10,h.at[1]-6];
lot.pointerMove(event(halfway));near(lot.lotHandles().find(h=>h.kind==='move').at,halfway);
assert.equal(operations.length,0);near(b.position,before.position);
lot.pointerMove(event(end));await release(end);
assert.equal(operations.length,1);assert.equal(operations[0].op,'move_building');
near(b.position,[before.position[0]-10,before.position[1]-6]);assert.equal(b.rotation,270);
console.log('  ok a 270-degree building previews in lot feet and posts once on release');

look();operations=[];before={position:[...b.position],rotation:b.rotation};
const pivot=lot.lotHandles().find(h=>h.kind==='move').at;
h=press('turn');const arm=h.at.map((v,i)=>v-pivot[i]);
const turned=rot(arm,-88).map((v,i)=>v+pivot[i]);lot.pointerMove(event(turned));await release(turned);
assert.equal(b.rotation,180);assert.equal(operations.length,1);assert.equal(operations[0].op,'rotate_building');
near(operations[0].about,pivot);near(at(boundsCentre),pivot);
console.log('  ok quarter-turn snapping sends rotate_building with a fixed lot-foot about');

// Move to within half a foot of a footprint turned four degrees from the house.
look();operations=[];
const targetPosition=[b.position[0]-3,b.position[1]-2.5];
const target=outline.map(p=>at(p,targetPosition,b.rotation+4));
read.suggestions=[{id:'suggestion',state:'open',outline:target}];
const ownCentre=outline.reduce((sum,p)=>sum.map((v,i)=>v+p[i]/outline.length),[0,0]);
const oldCentre=at(ownCentre), wantCentre=target.reduce((sum,p)=>sum.map((v,i)=>v+p[i]/target.length),[0,0]);
h=press('move');const drop=h.at.map((v,i)=>v+wantCentre[i]-oldCentre[i]+(i===0?.5:0));
lot.pointerMove(event(drop));await release(drop);
// A snap that turns is one round: a single rotate_building about the motion's fixed point.
assert.equal(operations.length,1);assert.equal(operations[0].op,'rotate_building');assert.equal(operations[0].about.length,2);
outline.forEach((p,i)=>near(at(p),target[i]));near([b.rotation],[184]);
assert.equal(snapFootprint({...b,position:[b.position[0]+8,b.position[1]]},outline,read.suggestions),null);
assert.equal(snapFootprint({...b,rotation:200},outline,read.suggestions),null);
assert.deepEqual(lot.lotSuggestions(),[{id:'suggestion',outline:target,dashed:true}]);
console.log('  ok near corners and angle snap together; distant and misaligned drops do not');

look();operations=[];read.suggestions=[];paused=true;before={position:[...b.position],rotation:b.rotation};
h=press('move');const pauseDrop=[h.at[0]-5,h.at[1]+4];lot.pointerMove(event(pauseDrop));await release(pauseDrop);
assert.equal(operations.length,0);near(b.position,before.position);near(answer.position,[before.position[0]-5,before.position[1]+4]);
assert.equal(answer.rotation,before.rotation);assert.ok(lot.underlay().visible);
console.log('  ok fit-pause handles update only the answer preview and keep the underlay');

paused=false;look();h=press('move');lot.pointerMove(event([h.at[0]+7,h.at[1]+3]));
lot.pointerUp({pointerId:1},true);assert.equal(operations.length,0);near(b.position,before.position);
enabled=false;assert.deepEqual(lot.lotHandles(),[]);assert.equal(lot.pointerDown(event(h.at)),false);
enabled=true;selected={};view.pick=()=>null;read.lot=[[0,0],[150,0],[150,180],[0,180]];
globalThis.fetch=async(url,init)=>{
  const body=JSON.parse(init.body);calls.push({url,method:init.method,body});
  if(url.includes('/plot/suggestions/'))read.suggestions[0].state=body.action==='accept'?'accepted':'dismissed';
  if(init.method==='PATCH')sheets.place.buildings[0].footprint=body.footprint;
  return new Response('{}');
};
const card=()=>shell.children.find(n=>n.className==='place-card editor-lot-card');
const descendants=n=>[n,...n.children.flatMap(descendants)];
const click=async text=>{const control=descendants(card()).find(n=>n.textContent===text);assert.ok(control,text);control.dispatchEvent(new Event('click'));await new Promise(r=>setImmediate(r));};
const suggest=()=>{read.suggestions=[{id:'s1',name:'Shed',state:'open',outline:[[10,100],[20,100],[20,110],[10,110]],size_ft:[10,10]}];};
suggest();look();
assert.ok(lot.pointerDown(event([10.3,105])));await release([10.3,105]);
assert.equal(calls.length,0);await click('Accept');
assert.equal(calls.length,1);assert.equal(calls[0].method,'POST');
assert.deepEqual(calls[0].body,{action:'accept',read:'r1',name:'Shed',kind:'other'});
assert.deepEqual(lot.lotSuggestions(),[]);
suggest();assert.ok(lot.pointerDown(event([10.3,105])));await release([10.3,105]);await click('Dismiss');
assert.equal(calls.at(-1).body.action,'dismiss');
console.log('  ok clicking a dashed footprint offers the shared Accept/Dismiss card and sends the read id');

const count=calls.length;
assert.ok(lot.pointerDown(event([150,90])));await release([150,90]);assert.equal(calls.length,count);
await click('This edge is the street');assert.equal(calls.at(-1).method,'PUT');
assert.deepEqual(calls.at(-1).body,{street_edge:[1,2],footprints:[]});
console.log('  ok selecting an edge only offers the explicit street action');

sheets.place.buildings=[{id:'shed',name:'Shed',footprint:[[10,100],[20,100],[20,110],[10,110]]}];
lot.focusBuilding('shed');h=press('move');lot.pointerMove(event([h.at[0]+5,h.at[1]+4]));
await release([h.at[0]+5,h.at[1]+4]);
assert.equal(calls.at(-1).method,'PATCH');assert.match(calls.at(-1).url,/place\/buildings\/shed$/);
near(sheets.place.buildings[0].footprint[0],[15,104]);
lot.drawFootprint('shed');assert.ok(lot.pointerDown(event([20,90])));
lot.pointerMove(event([31,104]));await release([31,104]);
[[20,90],[31,90],[31,104],[20,104]].forEach((p,i)=>near(sheets.place.buildings[0].footprint[i],p));
assert.equal(calls.at(-1).body.footprint_from,'drawn');
console.log('  ok an unbuilt footprint can move and be redrawn in the scene');

abort.abort();assert.equal(sheet.parent,null);assert.equal(captures.size,0);view.dispose();
console.log('  ok cancellation, read-only state and disposal preserve the saved building');

// Final wave M3: the editor's first view comes from the street and no yard plant
// stands between it and the house. Checked by sampling each sight line against
// every plant's trunk-to-crown column (a quarter of its height across).
const {streetView, streetSegment} = await import(file('static/twin/editor/lot_tools.js'));
const houses = flat.buildings.flatMap(b => {
  const a = (b.rotation || 0) * Math.PI / 180;
  return b.walls.flatMap(w => [w.from, w.to]).map(p => [Math.cos(a) * p[0] - Math.sin(a) * p[1] + b.position[0], Math.sin(a) * p[0] + Math.cos(a) * p[1] + b.position[1]]);
});
const box = [0, 1].map(i => [Math.min(...houses.map(p => p[i])), Math.max(...houses.map(p => p[i]))]);
const middle = box.map(([lo, hi]) => (lo + hi) / 2);
const hidden = (eye, target) => flat.site.planting.some(p => {
  for (let i = 1; i < 200; i++) {
    const t = i / 200, q = [0, 1, 2].map(k => eye[k] + (target[k] - eye[k]) * t);
    if (Math.hypot(q[0] - p.at[0], q[1] - p.at[1]) < p.height / 4 && q[2] < p.height) return true;
  }
  return false;
});
const span = Math.max(box[0][1] - box[0][0] + 7, box[1][1] - box[1][0], 20), k = span / 38;
assert.ok(hidden([middle[0] - 41 * k, middle[1] - 69 * k, 22 * k], [...middle, 8]), 'the old fixed Front looks through the street trees');
const lotOutline = flat.site.lot, south = [lotOutline[1], lotOutline[2]];
assert.deepEqual(streetSegment({lot: {read: {street_edge: [1, 2], lot: lotOutline}}}, flat), south);
assert.deepEqual(streetSegment({lot: {read: null, placement: {street_edge: [1, 2]}}}, flat), south);
assert.equal(streetSegment({lot: {read: null, placement: null}}, flat), null);
for (const [street, side] of [[south, eye => eye[1] < box[1][0]], [[lotOutline[0], lotOutline[1]], eye => eye[0] > box[0][1]], [null, eye => eye[1] < middle[1]]]) {
  const view = streetView(flat, street);
  assert.ok(view && side(view.position), ['the eye stands on the street side', street, view?.position]);
  assert.deepEqual(view.target, [...middle, 8]);
  for (const sight of [view.target, ...[[box[0][0], box[1][0]], [box[0][1], box[1][0]], [box[0][1], box[1][1]], [box[0][0], box[1][1]]].map(p => [(p[0] + middle[0]) / 2, (p[1] + middle[1]) / 2, 8])])
    assert.ok(!hidden(view.position, sight), ['no plant stands in the sight line', street, view.position, sight]);
  assert.ok(Math.hypot(view.position[0] - middle[0], view.position[1] - middle[1]) > span, 'framed from a distance, not inside the house');
}
assert.equal(streetView({buildings: [], site: {}}, south), null);
console.log('  ok the first view comes from the street and past the yard plants');
console.log('10/10 passed');
"""


def run():
    from services.twin_model_bridge import assemble, flatten
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    flat = flatten(assemble(fixture)[0])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths = []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'flat': flat, 'kit': kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_lot_', delete=False) as f:
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
