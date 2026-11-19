"""Split card, armed scene routing and topology, without a browser."""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DRIVER = r"""
const THREE = await import('three');
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {applyLocal,LocalMissing} = await import(file('static/twin/editor/local_ops.js'));
const wall={id:'w',level:'L',joints:['a','b'],from:[0,0],to:[10,0],height:9,thickness:.5,kind:'solid'};
const plan={buildings:[{id:'B',position:[0,0],levels:[{id:'L',elevation:0,ceiling:9}],
  joints:[{id:'a',level:'L',at:[0,0]},{id:'b',level:'L',at:[10,0]}],walls:[wall],rooms:[],
  openings:[{id:'o1',wall:'w',at:2,width:1},{id:'o2',wall:'w',at:7,width:1}],items:[],anchors:[]}],site:{}};
const saved=structuredClone(plan), operation={op:'split_wall',building:'B',wall:'w',at:4.25};
const split=applyLocal(plan,operation);assert.ok(split,'split must apply locally');
const b=split.plan.buildings[0];assert.equal(b.walls.length,2);assert.equal(b.joints.length,3);
assert.deepEqual(b.joints.find(j=>!['a','b'].includes(j.id)).at,[4.25,0]);
assert.equal(b.walls[0].joints[1],b.walls[1].joints[0]);assert.equal(b.walls[1].id,'w~2');
for(const w of b.walls)for(const key of ['height','thickness','kind'])assert.equal(w[key],wall[key]);
assert.deepEqual(b.openings.map(o=>[o.wall,o.at]),[['w',2],['w~2',2.75]]);
assert.deepEqual(plan,saved);assert.throws(()=>applyLocal(plan,{...operation,wall:'gone'}),LocalMissing);
const joinPlan=structuredClone(plan),jb=joinPlan.buildings[0];
jb.joints.push({id:'c',level:'L',at:[11,1]},{id:'d',level:'L',at:[11,8]});
jb.walls.push({...wall,id:'v',joints:['c','d'],from:[11,1],to:[11,8]});
const joined=applyLocal(joinPlan,{op:'move_joint',building:'B',joint:'b',to:[11,1]}).plan.buildings[0];
assert.equal(joined.joints.length,3);assert.ok(!joined.joints.some(j=>j.id==='b'));
assert.deepEqual(joined.walls[0].joints,['a','c']);assert.deepEqual(joined.walls[0].to,[11,1]);
assert.throws(()=>applyLocal({buildings:[joined]},{op:'move_joint',building:'B',joint:'b',to:[12,1]}),LocalMissing);
const {createDrag}=await import(file('static/twin/editor/drag.js'));
let drawn,released;
const drag=createDrag({model:()=>joinPlan,view:{screenOfFloor:(x,y)=>[x*100,y*100],floorAt:(x,y)=>[x/100,y/100],
 rebuildLevel:(_b,_l,p)=>drawn=p},onCommit:async(_op,{local})=>released=local});
assert.ok(drag.begin({kind:'joint',building:'B',id:'b'},[10,0]));drag.update([11,1]);
assert.equal(drawn.buildings[0].joints.length,4,'drag still holds the original joint graph');
await drag.finish();assert.equal(drawn.buildings[0].joints.length,3);assert.deepEqual(drawn,released);

const host=document.createElement('div'),canvas=document.createElement('canvas');document.body.append(host);host.append(canvas);
const controls=new Element('controls');controls.enabled=true;
const camera=new THREE.PerspectiveCamera();camera.position.set(0,10,10);camera.lookAt(0,0,0);
let picked='w';const ops=[],abort=new AbortController();
const view={renderer3:{domElement:canvas},camera,controls,state:{view:'B:L'},groups:{levels:{}},
  pickAll:()=>[{kind:'wall',id:picked,building:'B'}],setSelection(){},
  screenOfFloor:(x,y)=>[x*100,y*100],floorAt:(x,y)=>[x/100,y/100],rebuildLevel(){}};
const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>({}),getSheets:()=>({}),
  op:async op=>ops.push(op),canEdit:()=>true,signal:abort.signal,panel:{clearSelection(){}}});
tools.delegate({pointerArmedDown:event=>tools.pointerArmedDown(event)});
tools.select({id:'w',building:'B'});
async function arm(){const button=visibleButtons('Split wall')[0];assert.ok(button,'wall card has Split wall');click(button);await tick();
  assert.equal(document.getElementById('editor-status').textContent,'Click the wall where it should split. Esc cancels.');}
function press(x){fire(canvas,'pointerdown',{pointerId:1,button:0,clientX:x*100,clientY:0});fire(document,'pointerup',{pointerId:1,clientX:x*100,clientY:0});}
await arm();press(4.3);await tick();assert.deepEqual(ops,[operation]);
press(4);await tick();assert.equal(ops.length,1,'one-shot only');
await arm();press(5.4);await tick();assert.equal(ops.at(-1).at,5);
await arm();press(.5);await tick();assert.equal(ops.length,2);assert.equal(document.getElementById('editor-status').textContent,input.short);
await arm();press(9.01);await tick();assert.equal(ops.length,2,'inch snapping never rescues a click too close to the far end');
await arm();fire(document,'keydown',{key:'Escape'});press(4);await tick();assert.equal(ops.length,2);
await arm();picked='other';press(4);picked='w';press(4);await tick();assert.equal(ops.length,2);
// An elevated hit on a rotated, translated building must use the wall point.
plan.buildings[0].position=[20,30];plan.buildings[0].rotation=90;
view.pickAll=()=>[{kind:'wall',id:'w',building:'B',point:[20*.3048,8*.3048,-34.3*.3048]}];
view.floorAt=()=>[9,9];await arm();press(4.3);await tick();assert.equal(ops.at(-1).at,4.25);
assert.equal(controls.enabled,true);abort.abort();
console.log('PASS split topology, welded release, card, armed routing, inch/midpoint snap, refusal, Esc and other wall');
"""


def run():
    from services.twin_model_ops import _SHORT
    code, output = run_node(PRELUDE + DRIVER, {'root': ROOT.as_posix(), 'short': _SHORT})
    print(output, end='')
    assert code == 0, output


if __name__ == '__main__':
    run()
