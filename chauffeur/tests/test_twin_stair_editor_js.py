"""Real two-click add tool, shared card, and endpoint handle gestures in Node."""
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import(three);
const {createDraw}=await import(file('static/twin/editor/draw.js'));
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const errors=[],calls=[];window.showGlobalAlert=message=>errors.push(message);
const b={id:'b',position:[0,0],rotation:0,base:0,
 levels:[{id:'L1',elevation:0,ceiling:9},{id:'L2',elevation:9,ceiling:9},{id:'L3',elevation:10,ceiling:9}],
 rooms:[],walls:[],joints:[],openings:[],anchors:[],items:[],stairs:[]};
const plan={buildings:[b],site:{}};let writable=true,selected={kind:'stair',id:'s',building:'b',level:'L1'};
const canvas=document.createElement('canvas');document.body.append(canvas);
const camera=new THREE.PerspectiveCamera(50,1440/900,.01,1000);
camera.position.set(8*.3048,28*.3048,-6*.3048);camera.lookAt(new THREE.Vector3(8*.3048,0,-5*.3048));camera.updateMatrixWorld(true);
const controls=new THREE.EventDispatcher();controls.enabled=true;
const view={renderer3:{domElement:canvas},controls,camera,groups:{levels:{}},
 floorAt:(x,y)=>[x/20,y/20],screenOfFloor:(x,y)=>[x*20,y*20]};
const op=async operation=>{
 calls.push(operation);
 if(operation.op==='add_stair')b.stairs.push({...operation,id:'s',rise_to:9,risers:15});
 else Object.assign(b.stairs[0],operation);
};
const tools={floor:()=>({building:b,level:b.levels[0],key:'b:L1'}),selection:()=>({}),setTool(){},select(){}};
const abort=new AbortController();
const draw=createDraw({view,tools,getPlan:()=>plan,canEdit:()=>writable,op,gesture:f=>f(),signal:abort.signal,panel:{message:assert.fail}});
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
const clickPoint=async(x,y)=>{draw.pointerDown({pointerId:1,clientX:x*20,clientY:y*20});draw.pointerUp({pointerId:1,clientX:x*20,clientY:y*20},false);await settle();};
const card=document.getElementById('piece-card');
const field=title=>card.querySelector(`[aria-label="${title}"]`);
const cards=createCards({getPlan:()=>plan,getLabel:()=> 'Stair',canEdit:()=>writable,edit:assert.fail,op,ask(){},select(){}});
await fire(document.getElementById('rail-add-stair'),'click');await settle();
cards.draw(null);assert.equal(card.hidden,false,'selection polling preserves the Add stair card');
assert.equal(card.hidden,false);assert.equal(field('Rails').value,'both');
field('Style').value='open';await fire(field('Style'),'change');await settle();
await clickPoint(2,4);assert.equal(calls.length,0);
await clickPoint(14,4);assert.equal(calls.length,1);
assert.deepEqual(calls[0],{op:'add_stair',building:'b',level:'L1',width:3,to_level:'L2',style:'open',rail:'both',from:[2,4],to:[14,4]});
cards.draw({pieceId:'s',buildingId:'b'});
for(const [title,value,key] of [['Width (ft)','4','width'],['To level','L3','to_level'],['Style','solid','style'],['Rails','left','rail']]){
 const before=calls.length;field(title).value=value;await fire(field(title),'change');await settle();await cards.queue(async()=>{});
 assert.equal(calls.length,before+1);assert.deepEqual(calls.at(-1),{op:'update_stair',building:'b',id:'s',[key]:key==='width'?4:value});
}
field('Width (ft)').value='1';await fire(field('Width (ft)'),'change');await settle();
assert.ok(errors.pop().includes('2 to 8'));
// Camera rays hit the real start and upper endpoint, on their own horizontal planes.
const handles=createHandles({view,getPlan:()=>plan,getSelection:()=>selected,canEdit:()=>writable,
 drag:{lastDragFrameMs:null},onCommit:op,signal:abort.signal});
const event=at=>{const p=new THREE.Vector3(at[0]*.3048,at[2]*.3048,-at[1]*.3048).project(camera);
 return {clientX:(p.x+1)*720,clientY:(1-p.y)*450};};
assert.equal(handles.handles().length,2);
for(const [end,z] of [['to',9],['from',0]]){
 const start=[...b.stairs[0][end],z],destination=[start[0]+1,start[1]+1,z],before=calls.length;
 assert.ok(handles.begin(event(start)));handles.update(event(destination));handles.update(event(destination));
 assert.equal(calls.length,before);await handles.finish();assert.equal(calls.length,before+1);
 assert.deepEqual(calls.at(-1),{op:'update_stair',building:'b',id:'s',[end]:destination.slice(0,2)});
}
let before=calls.length;
assert.ok(handles.begin(event([...b.stairs[0].from,0])));await handles.finish();assert.equal(calls.length,before,'click without move is no op');
assert.ok(handles.begin(event([...b.stairs[0].to,9])));handles.update(event([19,6,9]));await handles.finish(true);assert.equal(calls.length,before,'cancel is no op');
writable=false;cards.draw();assert.equal(handles.handles().length,0);
assert.equal(handles.begin(event([...b.stairs[0].to,9])),false);
assert.ok(card.querySelectorAll('input, select').every(n=>n.disabled));
field('Style').value='open';await fire(field('Style'),'change');await settle();await cards.queue(async()=>{});assert.equal(calls.length,before);
await fire(document.getElementById('rail-add-stair'),'click');await settle();assert.equal(draw.pointerDown({clientX:20,clientY:20,pointerId:1}),false);
assert.deepEqual(errors,[]);
console.log('Passed: two clicks one add op, shared defaults/card updates, validation, both endpoint drags one op, cancel/no-op, read-only fields and no handles');
"""

if __name__ == '__main__':
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()})
    print(output)
    sys.exit(code or 0)
