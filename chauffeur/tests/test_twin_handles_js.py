"""CPU geometry proof for Task 12; Chromium input/round gates stay in t12 live.

Reuse Task 11's renderer and DOM doubles, with real household geometry and
three.js camera rays. Scratch files are direct children of system temp.
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

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const {createDrag} = await import(file('static/twin/editor/drag.js'));
const {createHandles} = await import(file('static/twin/editor/handles.js'));
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {hostPoint} = await import(file('static/twin/twin_hosts.js'));
const THREE = await import(three);
let passed = 0;
const ok = text => {passed++; console.log('  ok ' + text);};
const B = 'pool-house', K = 'room:5d7de10ca48340ae85c407d22337c6f7';
const W = 'wall:9adea4c38eb2430697cf47d4ddee9d2a';
const WEST = 'wall:17ec2a8dad9e47d0aefbfe143524c1c2~2', NORTH = 'wall:d60289b4c26b487db5145bdeb22d530e';
const O = 'opening:4009c0058fbc4f09bd0edbc4b2b0e4b5';
const building = flat.buildings.find(b => b.id === B);
building.anchors.push({id:'switch:t12',kind:'switch',offset:0,host:{wall:WEST,side:'left',at:2.5,z:4}});
building.items.push({id:'chair:t12',kind:'chair',offset:0,host:{floor:K,u:.25,v:.4}});
const host = new Element(), view = await mountTwin(host,{plan:flat,kit,tier:'low',preserveCamera:true});
view.showAnchors = true;
await view.setEditableLevel(B + ':L1'); view.setView(B + ':L1');
const abort = new AbortController(), ops = [];
let selected, handles, refuse = false, enabled = true;
const select = (kind,id) => {selected={kind,id,building:B,level:'L1',room:K};};
const commit = op => {ops.push(op);if(refuse)throw Error('server refused');};
const drag = createDrag({view,model:()=>flat,onPreview:p=>handles.show(p),onCommit:commit});
handles = createHandles({view,getPlan:()=>flat,getSelection:()=>selected,canEdit:()=>enabled,
  drag,onCommit:commit,signal:abort.signal});
function world(p) {
  const a=(building.rotation||0)*Math.PI/180,b=building.position||[0,0];
  return new THREE.Vector3((Math.cos(a)*p[0]-Math.sin(a)*p[1]+b[0])*.3048,
    (p[2]+(building.base||0))*.3048,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+b[1])*.3048);
}
function look(eye,target) {
  view.camera.position.copy(world(eye)); view.camera.lookAt(world(target)); view.camera.updateMatrixWorld(true);
}
function event(p) {
  const point=world(p).project(view.camera);
  return {clientX:(point.x+1)*720,clientY:(1-point.y)*450};
}
function down(p){assert.ok(handles.begin(event(p)),'handle answers its exact model point: '+p);}
async function reset(){await view.rebuild(flat);view.setView(B+':L1');ops.length=0;handles.show(null);}
const near=(a,b,tol=.01)=>assert.ok(Math.abs(a-b)<tol,`${a} is near ${b}`);

select('wall',W);
const wall=building.walls.find(w=>w.id===W), mid=wall.from.map((v,i)=>(v+wall.to[i])/2);
look([mid[0],mid[1]-.01,90],[...mid,0]);
assert.equal(handles.handles().filter(h=>h.kind==='wall').length,1);
assert.equal(handles.handles().filter(h=>h.kind==='joint').length,building.rooms.find(r=>r.id===K).joints.length);
down([...mid,0]); handles.update(event([mid[0],mid[1]-2,0]));
assert.equal(ops.length,0); near(view.plan.buildings.find(b=>b.id===B).walls.find(w=>w.id===W).from[1],mid[1]-2);
await handles.finish(); assert.equal(ops.length,1);assert.equal(ops[0].op,'move_wall');near(ops[0].by[1],-2);
ok('wall handle at floor level previews connected geometry and posts once on release');

await reset();select('room',K);
const corner=building.joints.find(j=>Math.hypot(j.at[0]-17.75,j.at[1]-17.333333333333332)<.01);
look([17.75,17.32,90],[17.75,17.33,0]);
down([...corner.at,0]);handles.update(event([corner.at[0]+1.5,corner.at[1]-1,0]));await handles.finish();
assert.equal(ops.length,1);assert.equal(ops[0].op,'move_joint');assert.equal(ops[0].joint,corner.id);
near(ops[0].to[0],corner.at[0]+1.5,.3);near(ops[0].to[1],corner.at[1]-1,.3);
ok('focused room corner dot gives move_joint without a selecting click');

await reset();select('room',K);look([8,7.99,90],[8,8,0]);
view.pick=()=>({kind:'room',id:K,building:B});
down([8,8,0]);handles.update(event([8,6,0]));await handles.finish();
assert.equal(ops.length,1);assert.equal(ops[0].op,'move_room');near(ops[0].by[1],-2);
ok('an open floor point gives one move_room');

await reset();select('opening',O);view.pick=()=>null;
const opening=building.openings.find(o=>o.id===O), west=building.walls.find(w=>w.id===WEST);
const at=a=>[0,west.from[1]-a,(opening.head+opening.sill)/2];
look([-25,at(opening.at)[1],at(opening.at)[2]+1],at(opening.at));
assert.deepEqual(handles.handles().filter(h=>h.kind.startsWith('opening')).map(h=>h.kind).sort(),
  ['opening_middle','opening_edge_left','opening_edge_right','opening_edge_top','opening_edge_bottom'].sort());
for(const [kind,start,end,field,amount] of [
  ['middle',at(opening.at),at(opening.at+2),'at',opening.at+2],
  ['left',at(opening.at-opening.width/2),at(opening.at-opening.width/2-1),'width',opening.width+1],
  ['right',at(opening.at+opening.width/2),at(opening.at+opening.width/2-1),'width',opening.width-1],
  ['top',[...at(opening.at).slice(0,2),opening.head],[...at(opening.at).slice(0,2),opening.head+.5],'head',opening.head+.5],
  ['bottom',[...at(opening.at).slice(0,2),opening.sill],[...at(opening.at).slice(0,2),opening.sill-.5],'sill',opening.sill-.5],
]) {
  ops.length=0;down(start);handles.update(event(end));assert.equal(ops.length,0);await handles.finish();
  assert.equal(ops.length,1);assert.equal(ops[0].op,kind==='middle'?'move_hosted':'resize_opening');near(ops[0][field],amount);
  if(kind==='left')near(ops[0].at+ops[0].width/2,opening.at+opening.width/2);
  if(kind==='right')near(ops[0].at-ops[0].width/2,opening.at-opening.width/2);
  await view.rebuild(flat);view.setView(B+':L1');
}
ok('five exact opening points slide, keep opposite edges fixed, and change head/sill');

await reset();select('anchor','switch:t12');
look([7,11,5],[.5,16.6,4]);
const switchPiece=building.anchors.find(a=>a.id==='switch:t12'), p=hostPoint(building,switchPiece.host);
down(p);handles.update(event([.25,west.from[1]-1,4]));await handles.finish();
assert.equal(ops.length,1);assert.equal(ops[0].op,'move_hosted');assert.equal(ops[0].host.wall,WEST);
assert.equal(ops[0].host.side,'left');near(ops[0].host.at,1);near(ops[0].host.z,4);
ok('hosted handle slides on the actual wall face');

await reset();select('anchor','switch:t12');look([7,11,5],[.5,16.6,4]);
down(p);
for(const point of [[.25,west.from[1]-.45,4],[.6,west.from[1]-.25,4],[1.5,west.from[1]-.25,4]])handles.update(event(point));
await handles.finish();assert.equal(ops.length,1);assert.equal(ops[0].host.wall,NORTH);
assert.equal(ops[0].host.side,'right');near(ops[0].host.at,1.5);near(ops[0].host.z,4);
assert.equal(building.anchors.find(a=>a.id==='switch:t12').host.wall,WEST,'source stays immutable');
ok('camera ray crossing the inside corner rehosts the same switch to the adjacent face');

await reset();select('item','chair:t12');
const chair=building.items.find(i=>i.id==='chair:t12'), chairAt=hostPoint(building,chair.host);
look([chairAt[0],chairAt[1]-.01,60],chairAt);
down(chairAt);handles.update(event([chairAt[0]+1,chairAt[1]+1,chairAt[2]]));await handles.finish();
assert.equal(ops.length,1);assert.equal(ops[0].op,'move_hosted');assert.equal(ops[0].host.floor,K);
const movedChair=hostPoint(building,ops[0].host);near(movedChair[0],chairAt[0]+1);near(movedChair[1],chairAt[1]+1);near(movedChair[2],chairAt[2]);
ok('hosted floor item slides in plan and retains its floor height');

await reset();select('opening',O);look([-25,at(opening.at)[1],at(opening.at)[2]+1],at(opening.at));
down(at(opening.at));handles.update(event(at(opening.at+1)));await handles.finish(true);
assert.equal(ops.length,0);assert.equal(view.plan,flat);assert.equal(selected.id,O);
refuse=true;down(at(opening.at));handles.update(event(at(opening.at+1)));
await assert.rejects(handles.finish(),/server refused/);assert.equal(ops.length,1);assert.equal(view.plan,flat);assert.equal(selected.id,O);
enabled=false;assert.deepEqual(handles.handles(),[]);assert.equal(handles.begin(event(at(opening.at))),false);
ok('cancel posts nothing, server refusal rolls back, selection persists, and read-only hides handles');

enabled=true;refuse=true;ops.length=0;
const left=at(opening.at-opening.width/2), inverted=at(opening.at+opening.width);
down(left);handles.update(event(inverted));
view.scene.traverse(o=>{const p=o.geometry?.attributes.position;if(p)for(const v of p.array)assert.ok(Number.isFinite(v));});
await assert.rejects(handles.finish(),/server refused/);assert.equal(ops.length,1);assert.ok(ops[0].width<0);
assert.equal(view.plan,flat);
ok('an invalid edge release still posts to the server while drawable buffers stay finite');

// R42: a CPU scene count, explicitly excluding the stubbed yard and GPU passes.
building.anchors=building.anchors.filter(a=>a.id!=='switch:t12');
building.items=building.items.filter(i=>i.id!=='chair:t12');
await view.rebuild(flat);view.setView(B+':L1');
const {createSelection}=await import(file('static/twin/editor/selection.js'));
createSelection({view,getModel:()=>flat}).focusRoom(K,B);
let submissions=0;
view.scene.traverse(o=>{
  if(!(o.isMesh||o.isLine)||!o.layers.test(view.camera.layers))return;
  for(let p=o;p;p=p.parent)if(!p.visible)return;
  submissions+=Array.isArray(o.material)?o.geometry.groups.length:1;
});
console.log(`Focused household CPU house mesh/line submissions (yard stubbed): ${submissions}`);
abort.abort();view.dispose();
console.log(`${passed}/${passed} passed`);
"""


# Match the editor's order: mount an empty scene, attach its tools, then load
# the model. This runs in a separate Node process with a hard deadline.
BOOT_DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const {hostPoint}=await import(file('static/twin/twin_hosts.js'));
const B='pool-house', K='room:5d7de10ca48340ae85c407d22337c6f7', W='wall:17ec2a8dad9e47d0aefbfe143524c1c2~2';
const nodes=new Map();
Element.prototype.getAttribute=function(k){return this[k];};
Element.prototype.querySelectorAll=function(){return [];};
const doc=new Element();
doc.createElement=tag=>{const node=new Element();if(tag==='button')node.getBoundingClientRect=()=>({width:47,height:44});return node;};
doc.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
doc.querySelector=()=>null;doc.querySelectorAll=()=>[];globalThis.document=doc;
const b=flat.buildings.find(b=>b.id===B);
b.rooms.find(r=>r.id===K).name="Emma's Room";
b.anchors.push({id:'anchor:t12-switch',kind:'switch',offset:0,device:null,host:{wall:W,side:'left',at:2.5,z:4}});
const empty={buildings:[],site:{},materials:{}};
let current=empty;
const view=await mountTwin(new Element(),{plan:empty,kit,tier:'high',preserveCamera:true});
view.showAnchors=true;
const abort=new AbortController();
const tools=createSceneTools({view,getPlan:()=>current,getModel:()=>current,getSheets:()=>({}),edit:()=>{},op:()=>{},
  panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:abort.signal});
current=flat;await view.rebuild(current);tools.refresh();
assert.ok(view.pieceIds(B).includes('anchor:t12-switch'));
const point=hostPoint(b,b.anchors.find(a=>a.id==='anchor:t12-switch').host);
assert.ok(point.every(Number.isFinite));
const THREE=await import(three);
const world=p=>{
  const angle=(b.rotation||0)*Math.PI/180, pos=b.position||[0,0];
  return new THREE.Vector3((Math.cos(angle)*p[0]-Math.sin(angle)*p[1]+pos[0])*.3048,
    (p[2]+(b.base||0))*.3048,-(Math.sin(angle)*p[0]+Math.cos(angle)*p[1]+pos[1])*.3048);
};
const descendants=node=>node.children.flatMap(child=>[child,...descendants(child)]);
const waitReady=async()=>{while(!view.ready)await new Promise(r=>setTimeout(r,1));};
descendants(nodes.get('editor-floors')).find(n=>n.textContent==='All floors').dispatchEvent(new Event('click'));
await waitReady();
view.setCameraState({position:world([15.5,-60,30]).toArray(),target:world([15.5,11,8]).toArray()});
const target=world([15.5,11,8]).project(view.camera);
const canvas=view.renderer3.domElement;
for(const type of ['pointerdown','pointerup']) {
  const event=new Event(type,{bubbles:true});
  Object.assign(event,{pointerId:1,button:0,clientX:(target.x+1)*720,clientY:(1-target.y)*450});
  canvas.dispatchEvent(event);
}
assert.equal(tools.selection().kind,'building');assert.equal(tools.selection().id,B);
assert.equal(nodes.get('piece-card').children[0].textContent,b.name);
const floorButton=descendants(nodes.get('editor-floors')).find(n=>n.dataset.floor===B+':L1');
floorButton.dispatchEvent(new Event('click'));await waitReady();
assert.equal(tools.selection().kind,'level');assert.equal(tools.selection().id,'L1');
assert.equal(nodes.get('piece-card').children[0].textContent,b.levels.find(l=>l.id==='L1').name);
console.log('  ok exterior pointer tap and the actual Floors button open their building and level cards');
view.controls.dispatchEvent({type:'change'});
tools.select({pieceId:K,buildingId:B});
while(!view.ready)await new Promise(r=>setTimeout(r,1));
const project=view.screenOfFloor.bind(view),projections=[];
view.screenOfFloor=(x,y,key,height=0)=>{projections.push({x,y,key,height});return project(x,y,key,height);};
view.setCameraState({position:world([20,10,90]).toArray(),target:world([20,10,0]).toArray()});
projections.length=0;
tools.select({pieceId:W,buildingId:B});
const wall=b.walls.find(w=>w.id===W);
const assertTopProjected=()=>assert.ok(projections.some(p=>p.key===B+':L1'&&p.height===wall.height&&p.x===wall.from[0]&&p.y===wall.from[1]),
  'selected wall top is projected by dimensions.position()');
assert.equal(tools.selection().id,W);assertTopProjected();
const labels=()=>descendants(canvas.parentElement).filter(n=>n.dataset.dimension);
assert.ok(labels().some(n=>!n.hidden&&Number.isFinite(parseFloat(n.style.left))),'selection change positions rendered dimension buttons');
for(const node of labels())node.style.left='stale';
projections.length=0;await view.rebuild(current);assertTopProjected();
assert.ok(labels().every(n=>n.hidden||nodePositioned(n)),'real twinrebuilt event repositions retained buttons');
function nodePositioned(node){return node.style.left!=='stale'&&Number.isFinite(parseFloat(node.style.left));}
console.log('  ok actual wall selection and twinrebuilt both run height-aware dimension positioning');
view.setCameraState({position:world([7,11,5]).toArray(),target:world([.5,16.6,4]).toArray()});
const projected=world(point).project(view.camera);
assert.equal(view.pick((projected.x+1)*720,(1-projected.y)*450)?.id,'anchor:t12-switch',
  'the switch wins over its hosting wall on a real perspective ray');
tools.select({pieceId:'anchor:t12-switch',buildingId:B});
view.controls.dispatchEvent({type:'change'});tools.handles();
assert.equal(tools.selection().id,'anchor:t12-switch');
tools.select({pieceId:'opening:4009c0058fbc4f09bd0edbc4b2b0e4b5',buildingId:B});
assert.equal(nodes.get('piece-card').children[0].textContent,"Window, emma's room north wall");
abort.abort();view.dispose();
console.log('  ok high-tier editor startup with a wall switch, scene tools, camera change, hosted selection and R46 title form terminates');
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
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'flat': flat, 'kit': kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, prefix='chauffeur_handles_', delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        for driver, timeout in [(BOOT_DRIVER, 20), (DRIVER, 60)]:
            paths[0].write_text(driver, encoding='utf-8')
            result = subprocess.run([shutil.which('node'), str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=timeout)
            print(result.stdout, end='')
            if result.returncode:
                raise AssertionError(result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
