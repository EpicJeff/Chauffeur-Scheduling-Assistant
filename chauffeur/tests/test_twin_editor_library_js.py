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
doc.createElementNS = (_namespace, tag) => doc.createElement(tag);
doc.createTextNode = text => {const node = new Element(); node.textContent = text; return node;};
Element.prototype.click = function() {this.dispatchEvent(new Event('click'));};
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
  const thumb=doc.getElementById('library-entries').children.find(n=>n.dataset.item || n.dataset.material);thumb.dispatchEvent(event('pointerdown',120,150));
  const [x,y]=pixel(point);doc.dispatchEvent(event('pointerup',x,y));await settle();
};
tools.select({pieceId:room.id,buildingId:b.id});while(!view.ready)await settle();
look([16.9,-25,6.5],[16.9,0,5.5]);await drop([16.9,0,5.5]);
const chooser=descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser');
assert.ok(chooser,'real pointer drop opens the chooser');
assert.deepEqual(chooser.children.map(n=>n.textContent),['This wall face','This room','This floor','The whole building','Cancel']);
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
const equipment=doc.getElementById('library-entries').children.filter(n=>n.dataset.equipment);
assert.deepEqual(equipment.map(n=>n.getAttribute('aria-label')),['Meter','Electric panel','Charger','Parking spot']);
assert.ok(equipment.every(n=>n.children.some(c=>c.tag==='svg')));
let pickedEquipment=null;doc.getElementById('rail-add-charger').addEventListener('click',()=>{pickedEquipment='charger';});
equipment[2].click();assert.equal(pickedEquipment,'charger');
ok('equipment library shows four icons and invokes the charger placement tool');

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
// Final wave I3: the card's Change opens the same list on its materials; a
// thumbnail pressed there (a button, so Enter and Space press it too) opens the
// same scope chooser, which now offers This floor (I4, R17).
const {createCards} = await import(file('static/twin/editor/cards.js'));
const cards = createCards({getPlan:()=>flat,getKit:()=>kit,getLabel:()=>'the piece',edit:op,op,canEdit:()=>true,
  select(){},ask(){},pickMaterial:s=>library.pick(s)});
const card = () => descendants(doc.getElementById('piece-card'));
const labelled = text => card().find(n=>n.tag==='label'&&n.textContent===text);
panel.hidden=true;
cards.draw({pieceId:front.id,buildingId:b.id});
const changes=card().filter(n=>n.textContent==='Change');
assert.equal(changes.length,2,'each face line offers Change');
changes[1].dispatchEvent(new Event('click'));await settle();
assert.equal(panel.hidden,false,'Change opens the library');
assert.equal(doc.getElementById('library-status').textContent,'Choose a material for the outside face.');
const thumb=doc.getElementById('library-entries').children[0];assert.equal(thumb.tag,'button');
thumb.dispatchEvent(new Event('click'));await settle();
const picked=descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser');
assert.deepEqual(picked.children.map(n=>n.textContent),['This wall face','This room','This floor','The whole building','Cancel']);
picked.children[2].dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{level:front.level,role:'siding'},material:{id:finish.id,color:finish.color}});
assert.equal(doc.getElementById('library-status').textContent,'Drag a thumbnail onto the house or yard.');
thumb.dispatchEvent(new Event('click'));await settle();assert.equal(ops.length,0,'a thumbnail press outside Change never applies');
ok('card Change opens the library list; a pressed thumbnail applies at the chosen scope, This floor included');

// Final wave I4: a line from the building or the floor can be cleared there.
b.materials={...(b.materials||{}),siding:{id:'building_finish',color:'#223344'}};
cards.draw(null);cards.draw({pieceId:front.id,buildingId:b.id});
const outside = () => descendants(card().find(n=>n.className==='editor-material-line'&&n.children[0].children[0].textContent==='Outside'));
outside().find(n=>n.textContent==='Clear for the building').dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{building:b.id,role:'siding'},material:null});
const floor=b.levels.find(l=>l.id===front.level);floor.materials={siding:{id:'floor_finish',color:'#556677'}};
cards.draw(null);cards.draw({pieceId:front.id,buildingId:b.id});
assert.ok(!outside().some(n=>n.textContent==='Clear for the building'));
outside().find(n=>n.textContent==='Clear for this floor').dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{level:floor.id,role:'siding'},material:null});
delete floor.materials;
ok('a building or floor line clears that role from the card');

// Final wave I4: an item's card turns and sizes it; anchors and items set their offset.
b.items=[...(b.items||[]),{id:'item:test',asset:chair.id,host:{floor:room.id,u:.5,v:.5},rotation:0,scale:1,state:'settled'}];
b.anchors=[...(b.anchors||[]),{id:'anchor:test',kind:'switch',host:{wall:front.id,side:'left',at:2,z:4},offset:0,state:'settled'}];
const type = async (label,text) => {const input=labelled(label).children[0];input.value=text;input.dispatchEvent(new Event('change'));await settle();};
cards.draw({pieceId:'item:test',buildingId:b.id});
assert.equal(labelled('Size').children[0].value,'100');assert.equal(labelled('Turn').children[0].value,'0');
await type('Size','150');assert.deepEqual(ops.pop(),{op:'set',building:b.id,id:'item:test',field:'scale',value:1.5});
await type('Turn','90');assert.deepEqual(ops.pop(),{op:'set',building:b.id,id:'item:test',field:'rotation',value:90});
await type('Distance from surface',`1'-0"`);assert.deepEqual(ops.pop(),{op:'move_hosted',building:b.id,id:'item:test',offset:1});
cards.draw({pieceId:'anchor:test',buildingId:b.id});
assert.ok(labelled('Distance from surface')&&!labelled('Turn')&&!labelled('Size'));
await type('Distance from surface','3"');assert.deepEqual(ops.pop(),{op:'move_hosted',building:b.id,id:'anchor:test',offset:.25});
ok('item cards carry Turn and Size; anchor and item cards carry Distance from surface');
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
