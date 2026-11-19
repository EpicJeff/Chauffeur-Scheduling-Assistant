"""Precision gizmos through real CPU camera rays; no browser."""
import json
import sys
from pathlib import Path
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r"""
const THREE=await import(three);
const {createGizmo}=await import(file('static/twin/editor/gizmo.js'));
const {createTypedValue}=await import(file('static/twin/editor/typed_value.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {applyLocal}=await import(file('static/twin/editor/local_ops.js'));
const {createEditQueue}=await import(file('static/twin/editor/edit_queue.js'));
const host=document.createElement('div'),canvas=document.createElement('canvas');document.body.append(host);host.append(canvas);
canvas.getBoundingClientRect=()=>({left:0,top:0,right:1000,bottom:1000,width:1000,height:1000});
const camera=new THREE.OrthographicCamera(-20,20,20,-20,.01,1000);camera.position.set(0,100,.001);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
const world=p=>new THREE.Vector3(p[0]*.3048,(p[2]||0)*.3048,-p[1]*.3048);
const event=p=>{const v=world(p).project(camera);return {clientX:(v.x+1)*500,clientY:(1-v.y)*500,button:0};};
let plan={buildings:[{id:'b',position:[0,0],levels:[{id:'L',elevation:0}],walls:[],rooms:[],items:[{id:'chair',host:{ground:true,at:[0,0]},rotation:10}],anchors:[]}],
 site:{planting:[{id:'tree',at:[0,0]}],beds:[{id:'bed',polygon:[[-2,-2],[2,-2],[2,2],[-2,2]]}]},light_fixtures:{'light.a':[{id:'fixture:00000000-0000-4000-8000-000000000001',shape:'spot',ref:'absolute',at:[0,0,3],aim:[10,0,0]}]}};
let selected={kind:'planting',id:'tree'},tool='move',ops=[],previews=[];
const layer=document.createElement('div');host.append(layer);
const view={camera,renderer3:{domElement:canvas},controls:new THREE.EventDispatcher(),rebuildLevel:(b,l,p)=>previews.push(p),groups:{levels:{}}};
const typed=createTypedValue(layer);
const gizmo=createGizmo({view,layer,typed,getPlan:()=>plan,getSelection:()=>selected,getTool:()=>tool,op:(operation,options)=>{ops.push({operation,options});}});
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} near ${b}`);
const handle=kind=>{gizmo.draw();const h=gizmo.handles().find(h=>h.kind===kind);assert.ok(h,kind);return h;};
async function drag(kind,target,free=false,exact){const h=handle(kind);assert.ok(gizmo.begin(event(h.at),h));gizmo.update(event(target(h)),{free});await gizmo.commit(exact);return ops.at(-1).operation;}
let operation=await drag('gizmo_move_x',h=>[h.at[0]+3.2,h.at[1]+2,h.at[2]]);
assert.deepEqual(operation,{op:'move_site_item',list:'planting',index:0,at:[3,0]});
operation=await drag('gizmo_move_x',h=>[h.at[0]+3.2,h.at[1]+2,h.at[2]],true);near(operation.at[0],3.2);assert.equal(operation.at[1],0);
assert.deepEqual(gizmo.handles().map(h=>h.kind),['gizmo_move_x','gizmo_move_y','gizmo_move_free']);
selected={kind:'item',id:'chair',building:'b',level:'L'};tool='rotate';
const rotate=(h,angle)=>{const a=angle*Math.PI/180,d=h.at.map((v,i)=>v-h.centre[i]);return [h.centre[0]+d[0]*Math.cos(a)-d[1]*Math.sin(a),h.centre[1]+d[0]*Math.sin(a)+d[1]*Math.cos(a),h.at[2]];};
operation=await drag('gizmo_turn',h=>rotate(h,50));near(operation.properties.rotation,55);
const h=handle('gizmo_turn');gizmo.begin(event(h.at),h);gizmo.update(event(rotate(h,50)),{free:false});
for(const key of ['3','3'])assert.equal(gizmo.key({key}),'typing');assert.equal(gizmo.key({key:'Enter'}),'commit');await gizmo.commit(gizmo.typedValue());near(ops.at(-1).operation.properties.rotation,43);
tool='scale';operation=await drag('gizmo_scale',h=>h.at.map((v,i)=>h.centre[i]+2*(v-h.centre[i])));near(operation.properties.scale,2);
operation=await drag('gizmo_scale_x',h=>h.at.map((v,i)=>h.centre[i]+2*(v-h.centre[i])));assert.deepEqual(operation.properties.scale_axes,[2,1,1]);
operation=await drag('gizmo_scale_y',h=>h.at, false,3);assert.deepEqual(operation.properties.scale_axes,[1,1,3]);
for(const [value,want] of [[100,20],[-2,.05]]){operation=await drag('gizmo_scale',h=>h.at,false,value);near(operation.properties.scale,want);}
assert.ok(previews.length);
selected={kind:'beds',id:'bed'};tool='rotate';operation=await drag('gizmo_turn',h=>rotate(h,50));assert.equal(operation.op,'update_site_shape');near(operation.rotation,45);assert.ok(operation.polygon);
tool='select';gizmo.draw();assert.equal(layer.querySelectorAll('[data-gizmo]').length,0);
const abort=new AbortController(),shapeHandles=createHandles({view,getPlan:()=>plan,getSelection:()=>selected,getTool:()=>tool,canEdit:()=>true,drag:{},signal:abort.signal});
const descriptors=shapeHandles.handles();assert.ok(descriptors.some(h=>h.kind==='site_vertex'));assert.ok(descriptors.some(h=>h.kind==='site_insert'));
assert.equal(descriptors.some(h=>['object_rotate','object_scale','site_rotate','site_scale'].includes(h.kind)),false);abort.abort();
for(const kind of ['wall','room','building','device'])for(tool of ['move','rotate','scale']){selected={kind,id:'chair',building:'b'};gizmo.draw();assert.equal(gizmo.handles().length,0);}
selected={kind:'light_fixture',id:'fixture:00000000-0000-4000-8000-000000000001',entity_id:'light.a'};tool='move';operation=await drag('gizmo_move_y',h=>[h.at[0]+4,h.at[1]+3.2,h.at[2]]);assert.deepEqual(operation.change.at,[0,3,3]);assert.deepEqual(operation.change.aim,[10,3,0]);
tool='rotate';operation=await drag('gizmo_turn',h=>rotate(h,50));near(operation.change.rotation_deg,45);near(operation.change.aim[0],10/Math.SQRT2);near(operation.change.aim[1],10/Math.SQRT2);
tool='scale';gizmo.draw();assert.equal(gizmo.handles().length,0);
selected={kind:'planting',id:'tree'};tool='move';const cancelled=ops.length,move=handle('gizmo_move_free');gizmo.begin(event(move.at),move);gizmo.update(event([3,4,0]));await gizmo.finish(true);assert.equal(ops.length,cancelled);assert.equal(typed.editing(),false);
// A second queued change replays every transform over its new authoritative base.
const queue=createEditQueue({send:()=>new Promise(()=>{}),onChange(){},onStatus(){},onRefused(){},onSignedOut(){}});queue.base({plan});
for(const op of [{op:'set_object',building:'b',id:'chair',properties:{rotation:33,scale:2,scale_axes:[3,1,1]}},
 {op:'update_site_shape',list:'beds',index:0,polygon:[[0,0],[4,0],[4,4]],rotation:15}]){assert.ok(applyLocal(plan,op));queue.push({op});}
queue.base({plan:structuredClone(plan)});assert.equal(queue.shown().buildings[0].items[0].rotation,33);assert.equal(queue.shown().buildings[0].items[0].scale,2);assert.deepEqual(queue.shown().site.beds[0].polygon,[[0,0],[4,0],[4,4]]);
console.log('FIXTURE_OP_CHECK '+JSON.stringify({plan,operation}));
console.log('PASS gizmo move/turn/scale, exact typing, exclusions, fixtures, cancel and queued replay');
"""

if __name__ == '__main__':
    code, output = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix()})
    print('\n'.join(line for line in output.splitlines() if not line.startswith('FIXTURE_OP_CHECK ')))
    assert code == 0, output
    sys.path.insert(0, str(ROOT))
    from services.twin_fixtures import apply_op, validate
    check = json.loads(next(line.removeprefix('FIXTURE_OP_CHECK ') for line in output.splitlines() if line.startswith('FIXTURE_OP_CHECK ')))
    apply_op(check['plan'], check['operation'])
    fixture = check['plan']['light_fixtures']['light.a'][0]
    assert fixture['rotation_deg'] == 45
    for shape in ('point', 'spot'):
        value = {'id': fixture['id'], 'shape': shape, 'ref': 'absolute', 'at': [0, 0, 3], 'rotation_deg': 393}
        if shape == 'spot': value['aim'] = [10, 0, 0]
        assert validate(value)['rotation_deg'] == 33
    print('PASS real fixture server accepts point/spot rotation and the gizmo payload')
