"""Actual editor click/card wiring for roof zones and wall equipment under node."""
import sys
from twin_live_node_rig import run

DRIVER=r"""
const {createDraw}=await import(file('static/twin/editor/draw.js'));
const {createCards,findPiece}=await import(file('static/twin/editor/cards.js'));
const {SOLAR_DEFAULTS}=await import(file('static/twin/twin_solar.js'));
const ids=['draw-note','draw-tools','editor-drag-outline','draw-cancel','piece-card',...['draw-room','draw-wall','split-room','add-door','add-window','add-anchor','add-stair','add-solar-zone','add-meter','add-electric-panel','add-charger','add-parking','delete','add-level'].map(n=>'rail-'+n)];
for(const id of ids){const node=document.createElement('div');node.id=id;document.body.append(node);}
const b={id:'b',levels:[{id:'L1',elevation:0,ceiling:10}],joints:[],rooms:[],anchors:[],items:[],openings:[],
 walls:[{id:'wall',level:'L1',from:[0,0],to:[40,0],kind:'solid',thickness:.5}],
 roofs:[{id:'roof',level:'L1',area:[[0,0],[40,0],[40,30],[0,30]],edges:[]}],
 roof:{sections:[{id:'roof',kind:'flat',rect:[0,0,40,30],pitch:0,plate:10,overhang:0}]},solar_zones:[]};
const plan={buildings:[b]},ops=[],abort=new AbortController(),canvas=document.createElement('canvas');document.body.append(canvas);
let selectedRoom='focused-room',surface={building:b,kind:'roof',piece:b.roof.sections[0],point:[10,10,10]};
const view={renderer3:{domElement:canvas},controls:{enabled:true},state:{camera:'top'},setView(value){this.shown=value;},setCamera(value){this.state.camera=value;},floorAt:()=>[10,10],screenOfFloor:(x,y)=>[x,y]};
window.showGlobalAlert=message=>assert.fail(message);window.promptConfirm=async()=>true;
const tools={floor:()=>({building:b,level:b.levels[0],key:'b:L1'}),selection:()=>({room:selectedRoom}),setTool(){},select(value){selectedRoom=null;}};
const op=async operation=>{ops.push(operation);if(operation.op==='add_solar_zone')b.solar_zones.push({id:'z',...SOLAR_DEFAULTS,...operation});
 if(operation.op==='update_solar_zone')Object.assign(b.solar_zones[0],operation);
 if(operation.op==='set_solar_source')plan.solar_source_roof=operation.roof;};
const draw=createDraw({view,tools,getPlan:()=>plan,op,gesture:work=>work(),canEdit:()=>true,signal:abort.signal,onInteract(){},panel:{message:assert.fail},surfaceAt:()=>surface});
async function place(name){await press(document.getElementById('rail-'+name));draw.pointerDown({pointerId:1,clientX:100,clientY:100});draw.pointerUp({pointerId:1,clientX:100,clientY:100},false);await wait(30);}
await place('add-solar-zone');assert.equal(selectedRoom,null);assert.equal(view.shown,'ext');assert.equal(view.state.camera,'front');assert.equal(ops[0].op,'add_solar_zone');assert.deepEqual(ops[0].plane,[0,0,10]);assert.deepEqual(ops[0].rect,[8,7,12,13]);
console.log('  ok roof click clears room scope and adds the exact roof-plane rectangle');
let selected={pieceId:'z',buildingId:'b'};
const cards=createCards({getPlan:()=>plan,getLabel:()=> 'solar zone',getSelection:()=>({}),edit:assert.fail,op,canEdit:()=>true,select:v=>{selected=v;},ask(){}});
cards.draw(selected);const card=document.getElementById('piece-card');assert.ok(card.textContent.includes('1 panels'));
const count=card.querySelectorAll('input').find(n=>n.getAttribute('aria-label')==='Panel count (empty fills zone)');count.value='0';count.dispatchEvent(new Event('change'));await wait(30);
assert.equal(ops.at(-1).op,'update_solar_zone');assert.equal(ops.at(-1).count,0);assert.ok(card.textContent.includes('0 panels'));
await press(card.querySelectorAll('button').find(n=>n.textContent==='Solar ribbon starts here'));assert.equal(plan.solar_source_roof,'roof');assert.equal(ops.at(-1).building,'b');
assert.equal(findPiece(plan,'z','b').kind,'solar_zone');
console.log('  ok zone card changes count, reports laid-out panels and sets its source roof');
surface={building:b,kind:'wall',piece:b.walls[0],point:[13,0,4],side:'right'};
for(const [name,kind]of [['add-meter','meter'],['add-electric-panel','electric_panel'],['add-charger','charger']]){
 await place(name);assert.equal(ops.at(-1).op,'add_equipment');assert.equal(ops.at(-1).kind,kind);assert.deepEqual(ops.at(-1).host,{wall:'wall',side:'right',at:13,z:4});
}
console.log('  ok meter, panel and charger use the clicked wall side and height');

b.rooms=[{id:'garage',level:'L1',polygon:[[0,0],[40,0],[40,30],[0,30]]}];
await place('add-parking');assert.equal(ops.at(-1).kind,'parking');assert.deepEqual(ops.at(-1).host,{floor:'garage',u:.25,v:1/3});
view.floorAt=()=>[50,50];await place('add-parking');assert.deepEqual(ops.at(-1).host,{ground:true,at:[50,50]});
console.log('  ok parking clicks use a garage floor or the outdoor ground');
const {createEquipmentShelf}=await import(file('static/twin/editor/equipment_shelf.js'));
const changes=[],shelfHost=document.createElement('div'),shelfPiece={id:'evse',kind:'charger',name:'Wallbox',power:'sensor.missing',car:'absent'};
const shelf=createEquipmentShelf({canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op:async o=>{changes.push(o);shelfPiece[o.field]=o.value;},
 report:assert.fail,parseLength:x=>Number(x),feetInches:x=>String(x),api:async path=>({ok:true,json:async()=>path.includes('states')?
 {states:{'sensor.evse':{attributes:{unit_of_measurement:'W'}},'sensor.energy':{attributes:{unit_of_measurement:'kWh'}}}}:{cars:[{id:'ev',name:'EV'}]}})});
shelf.draw(shelfHost,{piece:shelfPiece,building:b});await wait(30);
const picker=shelfHost.querySelector('[data-equipment-field="power"]');assert.equal(picker.value,'sensor.missing');
assert.ok(picker.querySelectorAll('option').some(o=>o.value==='sensor.evse'));assert.ok(!picker.querySelectorAll('option').some(o=>o.value==='sensor.energy'));
picker.value='sensor.evse';picker.dispatchEvent(new Event('change'));await wait(30);assert.equal(changes.at(-1).value,'sensor.evse');
const carPicker=shelfHost.querySelector('[data-equipment-field="car"]');assert.equal(carPicker.value,'absent');carPicker.value='ev';carPicker.dispatchEvent(new Event('change'));await wait(30);
assert.equal(changes.at(-1).field,'car');assert.equal(changes.at(-1).value,'ev');
const parkingHost=document.createElement('div');shelf.draw(parkingHost,{piece:{id:'spot',kind:'parking'},building:b});
const rotation=parkingHost.querySelector('[data-equipment-field="rotation"]');rotation.value='90';rotation.dispatchEvent(new Event('change'));await wait(30);
assert.equal(changes.at(-1).value,90);assert.equal(changes.at(-1).id,'spot');
console.log('  ok charger and parking shelves keep saved choices, filter power and save car/rotation');
assert.deepEqual(domErrors,[]);assert.deepEqual(escaped,[]);abort.abort();console.log('5/5 energy editor checks passed');process.exit(0);
"""
if __name__=='__main__':sys.exit(run(DRIVER))
