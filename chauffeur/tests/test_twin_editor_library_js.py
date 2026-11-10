"""CPU event-path checks for the library; Chromium remains the controller's gate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_library_ui_'))
os.environ.pop('HA_BASE_URL', None)
from test_twin_drag_js import DRIVER as DRAG_DRIVER

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE = await import(three);
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {createLibrary, materialLines, surfaceOperation, itemOperation, wallFace} = await import(file('static/twin/editor/library.js'));
const nodes = new Map(), doc = new Element();
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
Element.prototype.getAttribute = function(k) {return this[k];};
Element.prototype.querySelectorAll = function(selector) {
  return descendants(this).filter(n => selector === 'button' ? n.tag === 'button' : selector === '[data-library-tab]' ? !!n.dataset.libraryTab : false);
};
Element.prototype.querySelector = function(selector) {return this.querySelectorAll(selector)[0] || null;};
Element.prototype.contains = function(node) {return node === this || descendants(this).includes(node);};
Element.prototype.focus = function() {};
Element.prototype.setPointerCapture = function(id) {this.capture = id;};
Element.prototype.hasPointerCapture = function(id) {return this.capture === id;};
Element.prototype.releasePointerCapture = function() {this.capture = null;};
Element.prototype.toDataURL = () => 'data:image/png;base64,preview';
doc.createElement = tag => {const node = new Element(); node.tag = tag; return node;};
doc.getElementById = id => {if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id);};
doc.querySelector = () => null; doc.querySelectorAll = () => []; globalThis.document = doc;
window.innerWidth = 1440; window.innerHeight = 900; window.showGlobalAlert = text => {throw Error(text);};
window.promptConfirm = async () => true;
const panel = doc.getElementById('library-panel'); panel.hidden = true;
for (const name of ['materials','items']) {const tab=doc.createElement('button');tab.dataset.libraryTab=name;panel.append(tab);}
panel.append(doc.getElementById('library-entries'));
const b = flat.buildings.find(b => b.id === 'pool-house'), room = b.rooms.find(r => r.name === 'Pool Lounge');
const front = b.walls.find(w => w.id === 'wall:44b42dc9c06144adbeaeb88ce33b0430');
const finish = {id:'red_brick_03',name:'Red brick 03',color:'#ad5946'};
const chair = {id:'mid_century_lounge_chair',name:'Lounge chair',kind:'furniture'};
let fetches = 0;
globalThis.fetch = async () => {fetches++;return {ok:true,status:200,text:async()=>JSON.stringify({materials:[finish],items:[chair]})};};
const ops = [], op = async operation => {ops.push(operation);};
const abort = new AbortController(), host = new Element(), view = await mountTwin(host,{plan:flat,kit,tier:'high',preserveCamera:true});
let library;
const tools = createSceneTools({view,getPlan:()=>flat,getModel:()=>flat,getKit:()=>kit,getSheets:()=>({}),op,edit:op,
  panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:abort.signal,pickSite:(x,y)=>library?.pickSite(x,y)});
library = createLibrary({view,kit,getPlan:()=>flat,tools,op,canEdit:()=>true,signal:abort.signal});
tools.delegate({pointerDown:library.pointerDown,pointerMove:library.pointerMove,pointerUp:library.pointerUp});
let passed=0;const ok = label => {passed++;console.log('  ok '+label);};
const record = {kind:'wall',piece:front,building:b};
assert.ok(materialLines(record,flat,kit).some(l=>l.text.endsWith(', from the building')));
front.faces={right:{id:finish.id,color:finish.color}};
assert.equal(materialLines(record,flat,kit).filter(l=>l.clear).length,1);
assert.equal(materialLines(record,flat,kit).find(l=>l.clear).text,'Red brick 03, set here');
tools.select({pieceId:front.id,buildingId:b.id});
const clear=descendants(doc.getElementById('piece-card')).find(n=>n.textContent==='Clear');clear.dispatchEvent(new Event('click'));
await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{wall:front.id,side:'right'},material:null});
delete front.faces;
const level=b.levels.find(l=>l.id===front.level);level.materials={siding:{id:'level_finish',color:'#334455'}};
assert.ok(materialLines(record,flat,kit).some(l=>l.text==='Level finish, from the level'));delete level.materials;
const inside=wallFace(b,front,'left');assert.equal(inside.room.id,room.id);
room.wall_material={id:'room_finish',color:'#445566'};
assert.ok(materialLines(record,flat,kit).some(l=>l.text==='Room finish, from the room'));delete room.wall_material;
assert.deepEqual(surfaceOperation({building:b,piece:front,kind:'wall',side:'right',room,role:'siding'},'room',finish).target,{room:room.id,surface:'walls'});
ok('real card Clear posts once; material source follows face, room, level and building');

const world = p => {const a=(b.rotation||0)*Math.PI/180,pos=b.position||[0,0];return new THREE.Vector3(
  (Math.cos(a)*p[0]-Math.sin(a)*p[1]+pos[0])*.3048,(p[2]+(b.base||0))*.3048,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+pos[1])*.3048);};
const look = (eye,target) => view.setCameraState({position:world(eye).toArray(),target:world(target).toArray()});
const pixel = p => {const v=world(p).project(view.camera);return [(v.x+1)*720,(1-v.y)*450];};
const event = (type,x,y) => {const e=new Event(type);Object.assign(e,{pointerId:1,button:0,clientX:x,clientY:y});return e;};
const settle = async()=>{for(let i=0;i<10;i++)await new Promise(r=>setTimeout(r,0));};
doc.elementFromPoint=()=>view.renderer3.domElement;
doc.getElementById('editor-scene').parentElement=new Element();
const browse = async name => {panel.querySelectorAll('[data-library-tab]').find(n=>n.dataset.libraryTab===name).dispatchEvent(new Event('click'));await settle();};
doc.getElementById('rail-library').dispatchEvent(new Event('click'));await settle();
assert.equal(fetches,1);
const drop = async point => {
  const thumb=doc.getElementById('library-entries').children[0];thumb.dispatchEvent(event('pointerdown',120,150));
  const [x,y]=pixel(point);doc.dispatchEvent(event('pointerup',x,y));await settle();
};
tools.select({pieceId:room.id,buildingId:b.id});while(!view.ready)await settle();
look([16.9,-25,6.5],[16.9,0,5.5]);await drop([16.9,0,5.5]);
const chooser=descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser');
assert.ok(chooser,'real pointer drop opens the chooser');
assert.deepEqual(chooser.children.map(n=>n.textContent),['This wall face','This room','The whole building','Cancel']);
chooser.children[0].dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{wall:front.id,side:'right'},material:{id:finish.id,color:finish.color}});
ok('real thumbnail pointer drop resolves the rotated outside face and chosen material scope');
await browse('items');look([15.5,9,90],[15.5,9,0]);await drop([8,8,0]);
const added=ops.pop();assert.equal(added.op,'add_item');assert.equal(added.host.floor,room.id);
const xs=room.polygon.map(p=>p[0]),ys=room.polygon.map(p=>p[1]);
assert.ok(Math.abs(Math.min(...xs)+added.host.u*(Math.max(...xs)-Math.min(...xs))-8)<.1);
assert.ok(Math.abs(Math.min(...ys)+added.host.v*(Math.max(...ys)-Math.min(...ys))-8)<.1);
await browse('materials');await browse('items');assert.equal(fetches,1);
ok('floor drop posts a hosted item with room fractions; browsing reuses its catalog');

tools.select(null);while(!view.ready)await settle();
const tree=flat.site.planting.find(p=>p.id==='cmp-tree-1'),original=[...tree.at];
const lot=p=>new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048);
view.setCameraState({position:lot([original[0],original[1]-.01,300]).toArray(),target:lot([...original,0]).toArray()});
const screen=p=>{const v=lot([...p,0]).project(view.camera);return [(v.x+1)*720,(1-v.y)*450];};
const start=screen(original),end=screen([96,75]),canvas=view.renderer3.domElement;
canvas.dispatchEvent(event('pointerdown',...start));doc.dispatchEvent(event('pointerup',...start));
assert.equal(tools.selection().kind,'planting');assert.equal(tools.selection().id,tree.id);
canvas.dispatchEvent(event('pointerdown',...start));canvas.dispatchEvent(event('pointermove',...end));doc.dispatchEvent(event('pointerup',...end));await settle();
const moved=ops.pop();assert.equal(moved.op,'move_site_item');assert.equal(moved.index,flat.site.planting.indexOf(tree));
assert.ok(Math.hypot(moved.at[0]-96,moved.at[1]-75)<.1);assert.equal(view.controls.enabled,true);
const del=descendants(doc.getElementById('piece-card')).find(n=>n.textContent==='Delete');del.dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'delete_site_item',list:'planting',index:flat.site.planting.indexOf(tree)});
ok('canvas delegates select and move a yard tree; its card Delete uses the site operation');
abort.abort();view.dispose();console.log(`${passed}/${passed} passed`);
"""


def run():
    from services import twin_model_bridge, twin_model_ops, twin_library
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = twin_model_bridge.assemble(fixture)[0]
    # A library plant must be drawable and survive both normalize and compose.
    from services import twin_compose
    for asset, kind in [('Bush 1', 'shrub'), ('Pine Medium', 'tree')]:
        changed, _ = twin_model_ops.apply(model, {'op': 'add_site_item', 'list': 'planting', 'asset': asset, 'at': [20, 125]})
        flat = twin_model_bridge.flatten(changed)
        plant = flat['site']['planting'][-1]
        assert plant['preset'] == asset and plant['kind'] == kind and plant['height'] > 0 and plant['src']['person']
        rebuilt = twin_compose.compose(flat, twin_library.kit('modern_farmhouse'), seed=1)[0]
        assert any(p['id'] == plant['id'] for p in rebuilt['site']['planting'])
    print('  ok library plants carry drawable metadata and survive composition')
    if not shutil.which('node'):
        raise RuntimeError('Node is required')
    kit = twin_library.kit('modern_farmhouse')
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='library_events_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': twin_model_bridge.flatten(model), 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
