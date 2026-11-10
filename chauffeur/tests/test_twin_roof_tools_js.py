"""Task 14 CPU interaction proof; the controller owns Chromium acceptance."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as DRAG_DRIVER

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createRoofTools,roofEdge}=await import(file('static/twin/editor/roof_tools.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const THREE=await import(three);
const B='pool-house', b=flat.buildings.find(b=>b.id===B), roof=b.roofs.find(r=>r.id==='roof:c32cf56375f64ea9aeaa8b82fd39b4a9');
const nodes=new Map(), descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
Element.prototype.querySelectorAll=function(tag){return descendants(this).filter(n=>n.tag===tag);};
Element.prototype.getAttribute=function(k){return this[k];};
Element.prototype.setPointerCapture=function(id){this.pointer=id;};
Element.prototype.hasPointerCapture=function(id){return this.pointer===id;};
Element.prototype.releasePointerCapture=function(){this.pointer=null;};
const doc=new Element();
doc.createElement=tag=>Object.assign(new Element(),{tag});
doc.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
doc.querySelector=()=>null;doc.querySelectorAll=()=>[];globalThis.document=doc;
window.showGlobalAlert=message=>{throw Error(message);};
const view=await mountTwin(new Element(),{plan:flat,kit,tier:'low',preserveCamera:true});
const abort=new AbortController(), ops=[];
let selected={kind:'roof',id:roof.id,building:B,level:'L1'}, clicked=null, enabled=true, refused=false;
let commitChange=null;
const commit=async op=>{ops.push(op);if(refused)throw Error('refused');commitChange?.();};
const handles=createHandles({view,getPlan:()=>flat,getSelection:()=>selected,canEdit:()=>enabled,
  drag:{},onCommit:commit,onClick:h=>clicked=h,signal:abort.signal});
const world=p=>{
 const a=(b.rotation||0)*Math.PI/180,pos=b.position||[0,0];
 return new THREE.Vector3((Math.cos(a)*p[0]-Math.sin(a)*p[1]+pos[0])*.3048,
   (p[2]+(b.base||0))*.3048,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+pos[1])*.3048);
};
function look(p){view.camera.position.copy(world([p[0],p[1]-.01,p[2]+60]));view.camera.lookAt(world(p));view.camera.updateMatrixWorld(true);}
const event=p=>{const q=world(p).project(view.camera);return {clientX:(q.x+1)*720,clientY:(1-q.y)*450};};
const near=(a,b)=>assert.ok(Math.abs(a-b)<.09,`${a} near ${b}`);
let passed=0;const ok=text=>{++passed;console.log('  ok '+text);};
look([15.5,11,roof.plate]);
assert.equal(handles.handles().filter(h=>h.kind==='roof_edge').length,4);
const edge=roof.area.findIndex((p,i)=>p[1]===22&&roof.area[(i+1)%4][1]===22), frame=roofEdge(roof,edge);
const at=[...frame.a.map((v,i)=>(v+frame.b[i])/2),roof.plate];look(at);
assert.ok(handles.begin(event(at)));await handles.finish(true,true);assert.equal(clicked.edge,edge);assert.equal(ops.length,0);
ok('one handle per roof edge; a still click opens that exact edge without an operation');
for(const amount of [.6,3]){
 assert.ok(handles.begin(event(at)));handles.update(event([at[0],at[1]+amount,at[2]]));
 assert.equal(ops.length,amount===.6?0:1);assert.equal(roof.area[edge][1],22);
 await handles.finish();const op=ops.at(-1);assert.equal(op.op,'move_roof_edge');near(op.by,amount);assert.equal(op.detach,amount>1);
}
ok('horizontal roof-edge drags post once, grow outward and detach only beyond the wall threshold');
refused=true;assert.ok(handles.begin(event(at)));handles.update(event([at[0],at[1]+2,at[2]]));
await assert.rejects(handles.finish(),/refused/);assert.equal(roof.area[edge][1],22);refused=false;
ok('refused roof-edge drag restores its source model and handles');
const dormer=b.dormers[0];selected={kind:'dormer',id:dormer.id,building:B,level:'L1'};
let shown=handles.handles(), middle=shown.find(h=>h.kind==='dormer_middle');
assert.equal(shown.filter(h=>h.kind==='dormer_edge').length,2);look(middle.at);
assert.ok(handles.begin(event(middle.at)));handles.update(event([middle.at[0],middle.at[1]-3,middle.at[2]]));await handles.finish();
let op=ops.at(-1), axis=roofEdge(roof,dormer.edge).axis;
assert.equal(op.op,'move_dormer');near(op.at,dormer.at-3*axis[1]);assert.ok(!('width' in op));
const lower=shown.filter(h=>h.kind==='dormer_edge').sort((a,b)=>a.at[1]-b.at[1])[0];look(lower.at);
assert.ok(handles.begin(event(lower.at)));handles.update(event([lower.at[0],lower.at[1]-1,lower.at[2]]));await handles.finish();
op=ops.at(-1);near(op.width,5);near(op.at,dormer.at-.5*axis[1]);assert.equal(dormer.width,4);
ok('dormer middle slides along its own edge; resizing moves its centre and keeps the opposite side fixed');
enabled=false;assert.deepEqual(handles.handles(),[]);enabled=true;
const cards=createCards({getPlan:()=>flat,getLabel:()=> 'roof',canEdit:()=>true,edit:()=>{},op:commit,select(){},ask(){}});
cards.edge({id:roof.id,building:B,edge});
const card=nodes.get('piece-card');
const buttons=()=>descendants(card).filter(n=>n.tag==='button');
assert.deepEqual(buttons().filter(n=>['Sloped','Gable','Clipped'].includes(n.textContent)).map(n=>n.textContent),['Sloped','Gable','Clipped']);
buttons().find(n=>n.textContent==='Gable').dispatchEvent(new Event('click'));
await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).setting,'gable');assert.equal(ops.at(-1).edge,edge);
const input=descendants(card).find(n=>n.tag==='input');input.value='14';
const enter=new Event('keydown');Object.assign(enter,{key:'Enter'});input.dispatchEvent(enter);await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).pitch,14);
ok('edge card runs set_roof_edge for Gable and Enter saves the labelled Pitch input');
const tools=createSceneTools({view,getPlan:()=>flat,getModel:()=>flat,getSheets:()=>({}),edit(){},op:commit,
  panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:abort.signal});
const roofTools=createRoofTools({view,tools,getPlan:()=>flat,op:commit,canEdit:()=>true,panel:{message(){}},signal:abort.signal});
tools.chooseFloor(B+':L1');
const rooms=b.rooms.filter(r=>r.level==='L1'&&r.state!=='ghost');
tools.select({pieceId:rooms[0].id,buildingId:B});
const r=rooms[1], centre=[0,1].map(i=>r.polygon.reduce((n,p)=>n+p[i],0)/r.polygon.length);
look([...centre,0]);const screen=view.screenOfFloor(...centre,B+':L1');
for(const type of ['pointerdown','pointerup']){const e=new Event(type);Object.assign(e,{pointerId:15,button:0,shiftKey:true,clientX:screen[0],clientY:screen[1]});view.renderer3.domElement.dispatchEvent(e);}
assert.deepEqual(new Set(tools.selectedRooms()),new Set([rooms[0].id,r.id]));
nodes.get('rail-roof').dispatchEvent(new Event('click'));nodes.get('roof-over').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).op,'roof_over');assert.equal(ops.at(-1).rooms.length,2);
ok('Shift+click adds a neighbouring room through rooms-first focus, and Roof over this sends both rooms');
tools.select(null);nodes.get('roof-draw').dispatchEvent(new Event('click'));
look([34.5,11,0]);
for(const p of [[31,0],[38,0],[38,22],[31,22],[31,0]]){const e={...event([...p,0]),pointerId:16};assert.ok(roofTools.pointerDown(e));roofTools.pointerUp(e,false);}
await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).op,'draw_roof');assert.deepEqual(ops.at(-1).area,[[31,0],[38,0],[38,22],[31,22]]);
ok('Draw roof area closes a snapped rectilinear polygon and sends its four corners');
view.setView('ext');view.showLevels(null);await view.setEditableLevel(null);look([6,11,16.5]);
const picked=view.pick(...Object.values(event([6,11,16.5])));assert.equal(picked.kind,'roof');
nodes.get('roof-dormer').dispatchEvent(new Event('click'));const e={...event([6,11,16.5]),pointerId:17};roofTools.pointerDown(e);roofTools.pointerUp(e,false);
await new Promise(r=>setTimeout(r,0));op=ops.at(-1);assert.equal(op.op,'add_dormer');assert.equal(op.roof,roof.id);near(op.at,11);assert.equal(op.edge,dormer.edge);
ok('Add dormer takes a real roof pick and projects its position along the sloped eave');
const main=flat.buildings.find(b=>b.id==='main-house'), wing=main.roofs.pop();
tools.chooseFloor(main.id+':L1');tools.select({pieceId:'room:070aa0ca32b94170968a5e2cbf0fcc6f',buildingId:main.id});
commitChange=()=>{main.roofs.push(wing);commitChange=null;};
nodes.get('rail-roof').dispatchEvent(new Event('click'));nodes.get('roof-over').dispatchEvent(new Event('click'));
await new Promise(r=>setTimeout(r,0));
assert.equal(tools.selection().id,wing.id);assert.equal(tools.selection().room,null);
descendants(nodes.get('editor-floors')).find(n=>n.textContent==='All floors').dispatchEvent(new Event('click'));
assert.equal(tools.selection().kind,'roof');assert.equal(tools.selection().id,wing.id);
assert.equal(tools.handles().filter(h=>h.kind==='roof_edge').length,4);
ok('creating a roof exits room focus, selects the new roof and retains its edge handles in All floors');
abort.abort();view.dispose();console.log(`${passed}/${passed} passed`);
"""


def run():
    from services.twin_model_bridge import assemble, flatten
    from services import twin_model_ops
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    model = assemble(fixture)[0]
    roof = next(r for b in model['buildings'] if b['id'] == 'pool-house' for r in b['roofs']
                if r['id'] == 'roof:c32cf56375f64ea9aeaa8b82fd39b4a9')
    edge = next(i for i, p in enumerate(roof['area']) if p[0] == 0 and roof['area'][(i + 1) % 4][0] == 0)
    model, _ = twin_model_ops.apply(model, {'op': 'add_dormer', 'building': 'pool-house', 'roof': roof['id'],
                                          'edge': edge, 'at': 11, 'width': 4, 'pitch': 8})
    model, _ = twin_model_ops.apply(model, {'op': 'roof_over', 'building': 'main-house', 'rooms': [
        'room:070aa0ca32b94170968a5e2cbf0fcc6f', 'room:6ae35a0dcd044566b9f9956dd1b2b4e3',
        'room:942bc5d1218848bcac98523057e20e11']})
    wing = next(b for b in model['buildings'] if b['id'] == 'main-house')['roofs'][-1]
    assert len(wing['area']) == 4
    assert abs(max(p[0] for p in wing['area']) - 14.333) < .01
    assert min(p[1] for p in wing['area']) == 14.333333333333334
    assert max(p[1] for p in wing['area']) == 54
    assert all(e['setting'] == 'sloped' and e['pitch'] == 6 for e in wing['edges'])
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    paths = []
    try:
        for suffix, content in [('.mjs', DRIVER), ('.json', json.dumps({'root': ROOT.as_posix(), 'flat': flatten(model), 'kit': kit}))]:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix=suffix, delete=False) as f:
                paths.append(Path(f.name))
                f.write(content)
        result = subprocess.run(['node', str(paths[0]), str(paths[1])], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    run()
