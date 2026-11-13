"""Runtime proof for yard-room drawing, shared cards, HA linking and placement.

Uses the shipped HA-link DOM double and real Three.js scene/sprite classes;
browser visual review remains a separate Claude gate.
"""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_twin_ha_link_js import DRIVER as HA_DRIVER, ROOT


DRIVER = HA_DRIVER.split("const { createHaLink }")[0] + r"""
const THREE = await import(three);
const {createSiteDrawing} = await import(file('static/twin/editor/site_drawing.js'));
const {createHistory} = await import(file('static/twin/editor/history.js'));
const {drawSiteShapeShelf} = await import(file('static/twin/editor/site_shape_shelf.js'));
const {createCards} = await import(file('static/twin/editor/cards.js'));
const {createHaLink} = await import(file('static/twin/editor/ha_link.js'));
const {createDevicePlacement} = await import(file('static/twin/editor/device_placement.js'));
const {pathOutline} = await import(file('static/twin/path_shapes.js'));
const rect = [[0,0],[10,0],[10,10],[0,10]];
const plan = {buildings:[],materials:{},site:{lot:rect,yard_rooms:[{id:'yard',name:'Pool deck',polygon:rect,ha_area:null}],
 devices:[],terraces:[{id:'pad',polygon:rect,height:4,blend:0}]}};
for (const id of ['piece-card','rail-undo','rail-redo','device-tools','device-note','device-cancel']) ids.set(id,new El('div'));
El.prototype.select = function() { this.selectedText = true; };
El.prototype.setPointerCapture = function(id) {this.pointerCapture=id;};
El.prototype.hasPointerCapture = function(id) {return this.pointerCapture===id;};
El.prototype.releasePointerCapture = function() {this.pointerCapture=null;};
El.prototype.getBoundingClientRect = () => ({left:0,top:0,width:1000,height:800});
El.prototype.getContext = () => new Proxy({}, {get:(target,key)=>target[key] || (()=>{}),set:(target,key,value)=>(target[key]=value,true)});
const abort = new AbortController(), operations = [];
let round = 0;
const history = createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>true,refresh:async()=>{},signal:abort.signal});
const drawing = createSiteDrawing({getPlan:()=>plan,commit:operation=>history.perform(async()=>{operations.push(operation);round++;})});
drawing.start('yard_rooms');
for (const p of [[1,1],[8,1],[8,8],[1,8]]) drawing.add(p,true);
drawing.move([2,4],true);
assert.equal(operations.length,0,'drawing and preview have no save');
assert.equal(await drawing.finish(),true);
assert.equal(operations.length,1);assert.equal(round,1,'the completed region is one history step');
assert.deepEqual(operations[0],{op:'add_site_shape',list:'yard_rooms',name:'Yard room',polygon:[[1,1],[8,1],[8,8],[1,8]]});
assert.equal(await drawing.finish(),false);assert.equal(operations.length,1,'second finish cannot save again');
console.log('ok draw yard room is one operation and one history step');

const shelfOps=[],made=[];
let shelfPending=Promise.resolve();
for (const [kind,piece] of [['pool',{id:'pool',polygon:rect}],['hardscape',{id:'patio',polygon:rect}],['fire_pit',{id:'pit',at:[5,5],radius:2}]]) {
 const host=new El('div'),record={kind,index:0,piece};
 drawSiteShapeShelf(host,record,{canEdit:()=>true,queue:work=>shelfPending=shelfPending.then(work),op:async operation=>shelfOps.push(operation),
  report:error=>{throw error;},onMakeRoom:()=>made.push(kind)});
 const before=shelfOps.length;
 buttonNamed(host,'Make this a room').click();await shelfPending;await settle();
 assert.equal(shelfOps.length,before+1);
 assert.deepEqual(shelfOps.at(-1),{op:'make_yard_room',list:kind,id:piece.id});
 assert.equal(made.at(-1),kind,'the completion callback runs after save');
}
assert.deepEqual(made,['pool','hardscape','fire_pit']);
const path={id:'walk',name:'Garden walk',kind:'path',points:[[0,0],[10,0],[10,10]],width:4},pathHost=new El('div');
let pathMade=0;
drawSiteShapeShelf(pathHost,{kind:'hardscape',index:0,piece:path},{canEdit:()=>true,queue:work=>shelfPending=shelfPending.then(work),
 op:async operation=>shelfOps.push(operation),report:error=>{throw error;},onMakeRoom:()=>pathMade++});
const beforePath=shelfOps.length;buttonNamed(pathHost,'Make this a room').click();await shelfPending;await settle();
assert.equal(shelfOps.length,beforePath+1);assert.equal(pathMade,1);
assert.deepEqual(shelfOps.at(-1),{op:'add_site_shape',list:'yard_rooms',name:'Garden walk',polygon:pathOutline(path)});
assert.ok(shelfOps.at(-1).polygon.length>=6,'path region follows its full width and turn');
const shortcutPlan={buildings:[],site:{hardscape:[{id:'patio',polygon:rect}],yard_rooms:[]}},shortcutOps=[],shortcutSelections=[];
const shortcutCard=createCards({getPlan:()=>shortcutPlan,getLabel:()=> 'Patio',edit:()=>{},ask:()=>{},canEdit:()=>true,
 select:value=>shortcutSelections.push(value),op:async operation=>{shortcutOps.push(operation);
  shortcutPlan.site.yard_rooms.push({id:'new-yard',name:'Patio',polygon:rect});}});
shortcutCard.draw({pieceId:'patio',buildingId:null});
buttonNamed(ids.get('piece-card'),'Make this a room').click();await settle();
assert.deepEqual(shortcutOps,[{op:'make_yard_room',list:'hardscape',id:'patio'}]);
assert.deepEqual(shortcutSelections,[{pieceId:'new-yard',buildingId:null}]);
assert.equal(document.activeElement.getAttribute('aria-label'),'Name');assert.equal(document.activeElement.selectedText,true);
console.log('ok pool, patio and round fire pit shortcuts each issue one make_yard_room; path shortcut adds its outline once; card selects Name');

const yard = plan.site.yard_rooms[0], cardOps=[], selected=[];
let available=false,editable=true;
const catalogue={available:true,areas:[{area_id:'pool_area',name:'Pool area'}],floors:[],
 rooms:[{room:'yard',building:null,level:null,yard:true,ha_area:'pool_area'}],unlinked:[{area_id:'pool_area',name:'Pool area'}],
 devices:[{device_id:'lamp',name:'Pool lamp',kind:'light',area_id:'pool_area',auto:{yard:true,building:null,room:'yard',at:[5,5],z:0}}]};
const save=async operation=>{
 cardOps.push(operation);
 if(operation.op==='update_site_shape')Object.assign(yard,Object.fromEntries(Object.entries(operation).filter(([k])=>!['op','list','id','index'].includes(k))));
};
const link=createHaLink({api:{request:async()=>available?catalogue:{available:false},report:error=>{throw error;}},
 getPlan:()=>plan,onCommit:save,canEdit:()=>editable,signal:abort.signal});
await link.refresh();
const host=ids.get('piece-card');
const card=()=>createCards({getPlan:()=>plan,getLabel:()=>yard.name,edit:save,op:save,ask:()=>{},canEdit:()=>true,
 select:value=>selected.push(value),haLink:link});
let cards=card();cards.draw({pieceId:yard.id,buildingId:null});
let input=host.querySelector('input[aria-label="Name"]');
assert.ok(input);assert.equal(input.maxLength,40);assert.equal(input.minLength,1);
input.value='Pool lounge';input.dispatchEvent({type:'change'});await settle();
assert.equal(yard.name,'Pool lounge');assert.equal(cardOps.length,1);
input=host.querySelector('input[aria-label="Home Assistant area"]');assert.ok(input,'no HA keeps a plain area field');
input.value='Outdoor area';input.dispatchEvent({type:'change'});await settle();
assert.equal(yard.ha_area,'Outdoor area');
input=host.querySelector('input[aria-label="Home Assistant area"]');input.value='';input.dispatchEvent({type:'change'});await settle();
assert.equal(yard.ha_area,null,'empty area unlinks');
const deletePrompts=[];window.promptConfirm=async (...args)=>{deletePrompts.push(args);return true;};
plan.site.devices=[{id:'placed-lamp',device:'lamp',host:{yard_room:'yard',u:.2,v:.3},offset:1.75}];
const beforeDelete=cardOps.length;buttonNamed(host,'Delete').click();await settle();
assert.equal(cardOps.length,beforeDelete+1);
assert.deepEqual(cardOps.at(-1),{op:'delete_site_item',list:'yard_rooms',index:0});assert.equal(selected.at(-1),null);
assert.match(deletePrompts.at(-1)[1],/1 device will be unplaced/);
assert.match(deletePrompts.at(-1)[1],/remain in Home Assistant/);
assert.match(deletePrompts.at(-1)[1],/Undo restores the room and its placements/);
plan.site.devices=[];
assert.equal(alerts.length,0);
console.log('ok shared yard card saves name, no-HA area field/unlink and one delete operation');

// A late first HA read must replace the no-HA field on the existing card.
available=true;await link.refresh();cards.draw({pieceId:yard.id,buildingId:null});
assert.equal(!!host.querySelector('input[aria-label="Home Assistant area"]'),false,'connected card delegates to the shared picker');
let area=areaSelect(host);assert.ok(area);assert.ok(area.options.some(o=>o.value==='pool_area'));
const beforeLink=cardOps.length;area.value='pool_area';area.dispatchEvent({type:'change'});await settle();
assert.equal(cardOps.length,beforeLink+1);assert.deepEqual(cardOps.at(-1),{op:'update_site_shape',list:'yard_rooms',id:'yard',ha_area:'pool_area'});
assert.ok(words(host).includes('Pool lamp'),'yard devices use the shared room device rows');
choose=options=>options.find(o=>o.label==='Pool lounge · Yard')?.value;
const unlinked=link.buildingSection({id:'house',levels:[],rooms:[]});buttonNamed(unlinked,'Pool area').click();await settle();
assert.ok(choices.at(-1).options.some(o=>o.label==='Pool lounge · Yard'));
assert.equal(cardOps.at(-1).list,'yard_rooms');
console.log('ok connected yard card uses area picker and devices; unlinked area chooser includes yard rooms');

const canvas=new El('canvas'),camera=new THREE.PerspectiveCamera(45,1.25,.01,1000),scene=new THREE.Scene();
camera.position.set(0,15,15);camera.lookAt(0,0,0);camera.updateMatrixWorld(true);
let ground=[2,3];
const placements=[];
const tools={haLink:link,setTool:()=>{},selection:()=>({kind:'yard_rooms',id:'yard',building:null})};
const view={renderer3:{domElement:canvas},scene,camera,controls:{enabled:true},pick:()=>null,groups:{levels:{}}};
const placement=createDevicePlacement({view,tools,library:{ground:()=>ground,surfaceAt:()=>null,ceilingAt:()=>null},getPlan:()=>plan,
 op:async operation=>placements.push(operation),canEdit:()=>true,signal:abort.signal,prepare:()=>{}});
const click={button:0,pointerId:7,clientX:100,clientY:100};
link.draw(new El('div'),{kind:'yard_rooms',piece:yard,building:null});
buttonNamed(host,'Pick a spot').click();await settle();
assert.equal(ids.get('device-tools').hidden,false,'yard Pick a spot arms placement');
assert.match(ids.get('device-note').textContent,/inside the yard room/);
assert.equal(placement.pointerDown(click),true);assert.equal(view.controls.enabled,false);
assert.equal(placement.pointerUp(click,false),true);await settle();
assert.equal(placements.length,1);assert.deepEqual(placements[0],{op:'place_device',device:'lamp',host:{yard_room:'yard',u:.2,v:.3},offset:0});
assert.equal(view.controls.enabled,true);
placement.arm(catalogue.devices[0],'yard_room','yard');ground=[12,3];placement.pointerDown(click);placement.pointerUp(click,false);await settle();
assert.equal(placements.length,1,'outside the selected outline cannot place a device');assert.match(alerts.at(-1),/inside this yard room/);
placement.cancel();
plan.site.devices=[{id:'placed-lamp',device:'lamp',host:{yard_room:'yard',u:.2,v:.3},offset:1.75}];
placement.refresh();
let sprite=scene.getObjectByName('editor-device-markers').children[0];
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-8,`${a} != ${b}`);
assert.equal(sprite.visible,true);near(sprite.position.x,2*.3048);near(sprite.position.z,-3*.3048);near(sprite.position.y,(4+1.75)*.3048);
const heightHost=new El('div'),yardRecord={kind:'yard_rooms',piece:yard,building:null};
link.draw(heightHost,yardRecord);
const height=heightHost.querySelector('input[aria-label="Height above ground (ft)"]');
assert.ok(height,'saved yard device exposes its ground offset');assert.equal(Number(height.value),1.75);assert.equal(height.disabled,false);
height.dispatchEvent({type:'pointerdown',pointerType:'mouse'});
assert.equal(height.closest('.editor-device-row').pointerCapture,undefined,'typing height does not grab or drag the device row');
const beforeHeight=cardOps.length,savedHost=structuredClone(plan.site.devices[0].host);
height.value='3.5';height.dispatchEvent({type:'change'});await settle();
assert.equal(cardOps.length,beforeHeight+1);
assert.deepEqual(cardOps.at(-1),{op:'place_device',device:'lamp',host:savedHost,offset:3.5});
editable=false;link.draw(heightHost,yardRecord);
const readOnlyHeight=heightHost.querySelector('input[aria-label="Height above ground (ft)"]');
assert.equal(readOnlyHeight.disabled,true,'read-only height input is disabled');
const beforeReadOnly=cardOps.length;readOnlyHeight.value='5';readOnlyHeight.dispatchEvent({type:'change'});await settle();
assert.equal(cardOps.length,beforeReadOnly,'read-only change events cannot save');editable=true;
plan.site.devices=[];placement.refresh();sprite=scene.getObjectByName('editor-device-markers').children[0];
near(sprite.position.x,5*.3048);near(sprite.position.y,4*.3048);near(sprite.position.z,-5*.3048);
console.log('ok yard placement/outside refusal, saved/auto ground sprites, one height edit preserving host, input gesture and read-only height');
abort.abort();assert.equal(scene.getObjectByName('editor-device-markers'),undefined);
console.log('5 yard editor runtime checks passed');
"""


def run():
    with tempfile.TemporaryDirectory(prefix='chauffeur_yard_editor_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix()}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=90)
        print(result.stdout, end='')
        assert result.returncode == 0, result.stderr


if __name__ == '__main__':
    run()
