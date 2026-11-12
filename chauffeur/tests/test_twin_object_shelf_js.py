"""Object shelf events and object lamps in the existing real-light pool."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from twin_live_node_rig import PRELUDE, run

DRIVER = r"""
const objects = await import(file('static/twin/objects.js'));
window.twinObjectSchema = JSON.parse(readFileSync(root + '/static/twin/object_schema.json'));
const {drawObjectShelf} = await import(file('static/twin/editor/object_shelf.js'));
const host=document.createElement('div');document.body.append(host);
const record={piece:{id:'chair',at:[1,2]},kind:'furniture',index:0,building:null};
const saved=[];let pending=Promise.resolve();
drawObjectShelf(host,record,{canEdit:()=>true,queue:work=>pending=pending.then(work),op:async op=>saved.push(op),report:error=>{throw error;}});
const scale=host.querySelector('[aria-label="Scale (factor)"]');assert.ok(scale);scale.value='1.5';scale.dispatchEvent(new Event('change'));await pending;
assert.deepEqual(saved.pop(),{op:'set_object',list:'furniture',index:0,properties:{scale:1.5}});
const tint=host.querySelector('[aria-label="Material tint"]');tint.value='#abcdef';tint.dispatchEvent(new Event('change'));await pending;
assert.equal(saved.pop().properties.tint,'#abcdef');
const shadow=host.querySelector('[aria-label="Casts shadow"]');shadow.checked=false;shadow.dispatchEvent(new Event('change'));await pending;
assert.equal(saved.pop().properties.casts_shadow,false);
assert.ok(host.querySelector('details'));host.remove();
assert.deepEqual(domErrors,[]);console.log('ok actual shelf saves exact scale, tint and shadow through model ops');

// Hosted items use the card's Size/Turn fields, not the free-object shelf's
// Scale/Yaw fields. Exercise their real save queue and history together.
const {createCards}=await import(file('static/twin/editor/cards.js'));
const {createHistory}=await import(file('static/twin/editor/history.js'));
const card=document.createElement('aside');card.id='piece-card';document.body.append(card);
for(const id of ['rail-undo','rail-redo']){const button=document.createElement('button');button.id=id;document.body.append(button);}
let plan={buildings:[{id:'b',levels:[],walls:[],rooms:[],items:[{id:'imported-chair',kind:'imported',asset:'import-chair',host:{floor:'room',u:.5,v:.5}}]}],site:{}};
const item=()=>plan.buildings[0].items[0],snapshots=new Map([[1,structuredClone(plan)]]),operations=[],reverted=[],alerts=[];
let round=1,releaseSize,holdSize=false;
window.showGlobalAlert=text=>alerts.push(text);
const abort=new AbortController();let cards;
const history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,refresh:async()=>cards.draw(),signal:abort.signal});
const commit=operation=>history.perform(async()=>{
 operations.push(operation);
 if(holdSize&&operation.field==='scale'){holdSize=false;await new Promise(resolve=>releaseSize=resolve);}
 plan=structuredClone(plan);item()[operation.field]=operation.value;snapshots.set(++round,structuredClone(plan));cards.draw();
});
cards=createCards({getPlan:()=>plan,getLabel:()=> 'Imported chair',getKit:()=>({}),canEdit:()=>true,op:commit,edit:commit,ask(){},select(){}});
const selection={pieceId:'imported-chair',buildingId:'b'};
const inputFor=text=>card.querySelectorAll('label').find(label=>label.firstChild?.textContent===text)?.querySelector('input');
const until=async predicate=>{for(let i=0;i<200&&!predicate();i++)await wait(5);assert.ok(predicate(),'shelf save completes');};
globalThis.fetch=window.fetch=async(_url,options)=>{const {round:target}=JSON.parse(options.body);reverted.push(target);plan=structuredClone(snapshots.get(target));snapshots.set(++round,structuredClone(plan));return {ok:true,text:async()=>JSON.stringify({round})};};
cards.draw(selection);assert.equal(item().rotation,undefined);assert.equal(inputFor('Turn').value,'0');
// A previous Size response may arrive while the next field is being typed.
// Browser removal of a focused input does not emit its pending change event.
holdSize=true;const size=inputFor('Size');size.value='150';size.dispatchEvent(new Event('change'));await until(()=>!!releaseSize);
const turn=inputFor('Turn');turn.focus();turn.value='90';turn.dispatchEvent(new InputEvent('input',{bubbles:true}));
releaseSize();await until(()=>item().scale===1.5);await wait(10);
assert.ok(inputFor('Turn')===turn,'finishing Size must retain the focused Turn input');assert.equal(turn.isConnected,true);assert.equal(turn.value,'90');
turn.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));turn.blur();turn.dispatchEvent(new Event('change',{bubbles:true}));
await until(()=>item().rotation===90&&!document.getElementById('rail-undo').disabled);
const savedTurn=inputFor('Turn');savedTurn.dispatchEvent(new Event('change'));savedTurn.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));await wait(10);
assert.deepEqual(operations,[{op:'set',building:'b',id:'imported-chair',field:'scale',value:1.5},{op:'set',building:'b',id:'imported-chair',field:'rotation',value:90}]);
await press(document.getElementById('rail-undo'));await until(()=>reverted.length===1&&!document.getElementById('rail-redo').disabled);
assert.equal(item().rotation,undefined);assert.equal(item().scale,1.5,'one undo removes only Turn');
await press(document.getElementById('rail-undo'));await until(()=>reverted.length===2&&document.getElementById('rail-undo').disabled);
assert.equal(item().scale,undefined);assert.equal(document.getElementById('rail-undo').disabled,true,'Size and Turn added exactly two history steps');
await press(document.getElementById('rail-redo'));await until(()=>reverted.length===3&&!document.getElementById('rail-redo').disabled);
assert.equal(item().scale,1.5);assert.equal(item().rotation,undefined);
await press(document.getElementById('rail-redo'));await until(()=>reverted.length===4&&!document.getElementById('rail-undo').disabled);
assert.equal(item().rotation,90);assert.equal(document.getElementById('rail-redo').disabled,true);assert.deepEqual(alerts,[]);
abort.abort();card.remove();console.log('ok imported item Size then missing-zero Turn to 90 survives a delayed Size save; exactly one history step per edit, undo and redo');

const {mountModes}=await import(file('static/twin/live/modes.js'));
const controls=document.createElement('div');controls.id='twin-controls';document.body.append(controls);
const scene=new THREE.Scene(), lamp=objects.applyObject(new THREE.Mesh(new THREE.BoxGeometry(1,2,1),new THREE.MeshStandardMaterial()),
 {id:'lamp',object_kind:'lamp',light_entity:'light.desk',emissive_color:'#ffffff'},{units:1,id:'b:lamp'});scene.add(lamp);
const canvas=document.createElement('canvas');document.body.append(canvas);
const view={scene,tier:'low',renderer3:{domElement:canvas},camera:new THREE.PerspectiveCamera(),controls:{target:new THREE.Vector3()},
 groups:{levels:{'b:L1':new THREE.Group()}},plan:{buildings:[{id:'b',items:[{id:'lamp',host:{floor:'room',u:.5,v:.5}}],rooms:[{id:'room',level:'L1'}],walls:[],levels:[]}]} };
const states={'light.desk':{state:'on',attributes:{brightness:128,rgb_color:[0,64,255]}}};
const live={layout:()=>({markers:[],rooms:[]}),peek:()=>states,stale:()=>false,rooms:()=>[],subscribe:()=>()=>{},
 energy:()=>({}),setMode(){},getMode:()=> 'all'};
const modes=mountModes(view,live);modes.setMode('lights');
let rows=modes.lights();assert.equal(rows.length,1);assert.equal(rows[0].device,'object:b:lamp');assert.equal(rows[0].real,true);
assert.deepEqual(rows[0].rgb,[0,64,255]);assert.ok(Math.abs(lamp.material.emissiveIntensity-128/255)<.00001);
const pool=[];scene.traverse(o=>{if(o.isPointLight)pool.push(o);});assert.equal(pool.length,4);
const material=lamp.material;states['light.desk'].state='off';modes.update();assert.equal(material.emissiveIntensity,0);
states['light.desk'].state='on';modes.update();assert.equal(lamp.material,material);assert.equal(pool.filter(l=>l.parent).length,4);
view.groups.levels['b:L1'].visible=false;modes.draw();assert.equal(modes.lights()[0].real,false);
modes.stop();controls.remove();console.log('ok linked object lamp follows HA state in the same fixed four-light pool, retains material and follows floor visibility');
"""

if __name__ == '__main__':
    sys.exit(run(DRIVER, timeout=90))
