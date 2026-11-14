"""Exercise the new editor entry point and fields under Node, without Chromium."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_twin_drag_js import DRIVER as BASE

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE=await import(three);
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createTerrainTools,snapPadPoint}=await import(file('static/twin/editor/terrain_tools.js'));
const {foundationShelf}=await import(file('static/twin/editor/foundation_shelf.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const {createLibrary}=await import(file('static/twin/editor/library.js'));
const nodes=new Map(),shell=new Element();
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]);
document.createElement=tag=>{const n=new Element();n.tag=tag;n.isConnected=true;return n;};
document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
document.querySelector=selector=>selector==='.editor-shell'?shell:null;
document.querySelectorAll=()=>[];
Element.prototype.querySelectorAll=function(selector){return descendants(this).filter(n=>selector.split(',').includes(n.tag));};
Element.prototype.querySelector=function(selector){return descendants(this).find(n=>n['aria-label']===selector.match(/aria-label="([^"]+)"/)?.[1])||null;};
Element.prototype.getAttribute=function(k){return this[k];};
Element.prototype.setPointerCapture=function(id){this.capture=id;};
Element.prototype.hasPointerCapture=function(id){return this.capture===id;};
Element.prototype.releasePointerCapture=function(){this.capture=null;};
Element.prototype.prepend=function(...nodes){this.children.unshift(...nodes);for(const n of nodes)n.parentElement=this;};
Element.prototype.closest=()=>null;
Element.prototype.focus=function(){document.activeElement=this;};
window.showGlobalAlert=text=>{throw Error(text);};window.promptConfirm=async()=>true;
// The library's import panel (main, v2.499.813) reads its settings when the editor mounts.
// This rig has no server: answer those reads, so a real alert still fails the test.
const realFetch=globalThis.fetch;
globalThis.fetch=async(input,init)=>{const url=String(typeof input==='string'?input:input?.url||'');
  if(/api\/house\/editor\/import-settings/.test(url))return new Response(JSON.stringify({limit_mb:50,unpacked_limit_mb:200}),{status:200,headers:{'content-type':'application/json'}});
  if(/api\/house\/(editor|twin)\/imports/.test(url))return new Response('[]',{status:200,headers:{'content-type':'application/json'}});
  if(/api\/house\/(editor\/library|materials)$/.test(url))return new Response(JSON.stringify({materials:[{id:'red_brick_03',name:'Red brick',color:'#aa3322'}],items:[]}),{status:200,headers:{'content-type':'application/json'}});
  return realFetch(input,init);};
const plan={buildings:[],site:{lot:[[0,0],[40,0],[40,40],[0,40]],terraces:[],beds:[{id:'bed',polygon:[[5,5],[10,5],[10,10],[5,10]]}]},materials:{}};
// Terrain tools live in the editor: mount inside an editor shell, so the viewer's levels
// camera (slice 2c) never takes over the scene.
const editorHost=new Element();editorHost.closest=selector=>selector==='.editor-shell'?editorHost:null;
const view=await mountTwin(editorHost,{plan,kit,tier:'low',preserveCamera:true});
view.setCameraState({position:[20*.3048,80*.3048,-19.999*.3048],target:[20*.3048,0,-20*.3048]});
const abort=new AbortController(),ops=[];let writable=true;
const op=async operation=>{ops.push(operation);if(operation.op==='add_pad')plan.site.terraces.push({id:'pad',...operation,edges:operation.polygon.map(()=>({edge:'slope'}))});
  if(operation.op==='add_site_shape'){const value=plan.site[operation.list],created={id:'drawn-'+ops.length,...operation};
    if(Array.isArray(value))value.push(created);else plan.site[operation.list]=value?[value,created]:created;}
  if(operation.op==='update_pad')Object.assign(plan.site.terraces[0],operation);
  if(operation.op==='reorder_pad'){const from=plan.site.terraces.findIndex(p=>p.id===operation.id);plan.site.terraces.splice(operation.to,0,plan.site.terraces.splice(from,1)[0]);}
  if(operation.op==='delete_pad')plan.site.terraces=[];
};
let library;
const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>kit,getSheets:()=>({}),op,edit:op,
  panel:{clearSelection(){},focusSelection(){}},canEdit:()=>writable,signal:abort.signal,pickSite:(x,y)=>library?.pickSite(x,y)});
library=createLibrary({view,kit,getPlan:()=>plan,tools,op,canEdit:()=>writable,signal:abort.signal});
const terrain=createTerrainTools({view,tools,getPlan:()=>plan,op,canEdit:()=>writable,signal:abort.signal});
terrain.show();const card=descendants(shell).find(n=>n.id==='terrain-card');
let fieldHost=card;
const click=text=>{const b=descendants(card).find(n=>n.textContent===text);assert.ok(b,text);b.dispatchEvent(new Event('click'));};
const change=(title,value)=>{const input=descendants(fieldHost).find(n=>n['aria-label']===title);assert.ok(input,title);input.value=String(value);input.dispatchEvent(new Event('change'));};
click('Add pad');change('Pad height (ft)',-4);change('Blend (ft)',8);
const event=p=>{const v=new THREE.Vector3(p[0]*.3048,0,-p[1]*.3048).project(view.camera);return {button:0,pointerId:1,clientX:(v.x+1)*720,clientY:(1-v.y)*450};};
for(const p of [[15,15],[25,15],[25,25],[15,25]]){assert.ok(terrain.pointerDown(event(p)));terrain.pointerUp(event(p),false);}
click('Finish pad');await new Promise(r=>setTimeout(r,0));
assert.equal(ops[0].op,'add_pad');assert.equal(ops[0].height,-4);assert.equal(ops[0].blend,8);assert.equal(ops[0].polygon.length,4);
terrain.choose('terraces','pad');change('Edge 1','sharp');await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).edges[0].edge,'sharp');
change('Edge 1 Wall','timber');await new Promise(r=>setTimeout(r,0));
assert.deepEqual(ops.at(-1).edges[0].wall,{material:'timber',thickness_in:8,above_in:0});
change('Edge 1 Thickness (in)',12);await new Promise(r=>setTimeout(r,0));
change('Edge 1 Above ground (in)',9);await new Promise(r=>setTimeout(r,0));
const authoredWall={material:'timber',thickness_in:12,above_in:9};
assert.deepEqual(ops.at(-1).edges[0].wall,authoredWall);
change('Edge 2','sharp');await new Promise(r=>setTimeout(r,0));
assert.deepEqual(ops.at(-1).edges[0].wall,authoredWall,'editing another edge preserves wall');
change('Edge 2 Wall','block');await new Promise(r=>setTimeout(r,0));
change('Edge 2','slope');await new Promise(r=>setTimeout(r,0));
assert.ok(!ops.at(-1).edges[1].wall);assert.deepEqual(ops.at(-1).edges[0].wall,authoredWall);
change('Edge 1 Wall','');await new Promise(r=>setTimeout(r,0));assert.ok(!ops.at(-1).edges[0].wall);
assert.ok(!descendants(card).some(n=>n['aria-label']==='Edge 1 Thickness (in)'));
// An undo/server refresh restores the same fields and values.
plan.site.terraces[0].edges[0].wall={...authoredWall};terrain.refresh();
assert.equal(descendants(card).find(n=>n['aria-label']==='Edge 1 Wall').value,'timber');
assert.equal(descendants(card).find(n=>n['aria-label']==='Edge 1 Above ground (in)').value,9);
// The wall face takes a Library material through the shared slot: one update_pad per change.
{
  const face=()=>descendants(card).find(n=>n['aria-label']==='Change the edge 1 wall face material');
  assert.ok(face(),'a wall face slot under a built wall');
  assert.ok(descendants(card).some(n=>n.textContent==='Default: Timber'),'the default is the wall kind');
  face().dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,20));
  const brick=descendants(card).find(n=>n.dataset?.material==='red_brick_03');assert.ok(brick,'the Library material is offered');
  brick.dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,20));
  assert.deepEqual(ops.at(-1).edges[0].wall,{...authoredWall,materials:{face:{id:'red_brick_03'}}});
  plan.site.terraces[0].edges[0].wall={...authoredWall,materials:{face:{id:'red_brick_03'}}};terrain.refresh();
  face().dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,20));
  descendants(card).find(n=>n.textContent==='Use default').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,20));
  assert.deepEqual(ops.at(-1).edges[0].wall,authoredWall,'Use default drops the slot');
  plan.site.terraces[0].edges[0].wall={...authoredWall};terrain.refresh();
}
click('Up 0.5 ft');await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).height,-3.5);
const h=terrain.handles()[0];assert.ok(h);
const drag={button:0,pointerId:2,clientX:h.screen[0],clientY:h.screen[1]};
const beforeClick=ops.length;assert.ok(terrain.pointerDown(drag));terrain.pointerUp(drag,false);assert.equal(ops.length,beforeClick,'a corner click creates no history round');
const dragMaterials=new THREE.MeshStandardMaterial().id;
assert.ok(terrain.pointerDown(drag));terrain.pointerMove({...drag,clientX:drag.clientX+15});
assert.equal(new THREE.MeshStandardMaterial().id,dragMaterials+1,'wall-bearing pad drag creates no material');
terrain.pointerUp({...drag,clientX:drag.clientX+15},false);
await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).op,'update_pad');assert.notDeepEqual(ops.at(-1).polygon,ops[0].polygon);
plan.site.terraces.push({id:'upper',polygon:[[14,14],[27,14],[27,27],[14,27]],height:0,blend:6},
  {id:'distant',polygon:[[32,32],[36,32],[36,36],[32,36]],height:2,blend:0});
terrain.refresh();
const control=text=>descendants(card).find(n=>n.textContent===text);
assert.ok(control('Layer 1 of 3'));assert.equal(control('Send back').disabled,true);assert.equal(control('Bring forward').disabled,false);
const labels=descendants(view.renderer3.domElement.parentElement).filter(n=>n.className==='editor-terrain-label');
assert.equal(labels[0].textContent,'0 ft','a covered pad label follows the resulting surface');
click('Bring forward');await new Promise(r=>setTimeout(r,0));
assert.deepEqual(ops.at(-1),{op:'reorder_pad',id:'pad',to:1});assert.equal(plan.site.terraces[1].id,'pad');assert.ok(control('Layer 2 of 3'));
click('Bring forward');await new Promise(r=>setTimeout(r,0));assert.equal(plan.site.terraces[2].id,'pad');assert.equal(control('Bring forward').disabled,true);
click('Send back');await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'reorder_pad',id:'pad',to:1});
// The pads list reads like drawing-app layers: top first, stored order reversed.
const savedPads=plan.site.terraces;
plan.site.terraces=[{...savedPads[1],height:-4},{...savedPads[0],height:0},{...savedPads[2],height:3}];
terrain.choose('terraces','pad');
const padRows=()=>descendants(card).filter(n=>n.dataset.padId);
const grips=()=>descendants(card).filter(n=>n.className==='editor-pad-grip');
const rowText=row=>descendants(row).filter(n=>n.tag==='span').map(n=>n.textContent).join(' ');
assert.deepEqual(padRows().map(n=>n.dataset.padId),['distant','upper','pad']);
assert.ok(rowText(padRows()[0]).includes('Pad 3 · +3 ft'));
assert.ok(rowText(padRows()[1]).includes('Pad 2 · 0 ft'));
assert.ok(rowText(padRows()[2]).includes('Pad 1 · −4 ft'));
assert.ok(rowText(padRows()[2]).includes('Wall'),'wall badge follows any wall-bearing edge');
assert.ok(!rowText(padRows()[0]).includes('Wall'));
assert.deepEqual(padRows().map(n=>n['aria-pressed']),['false','false','true']);
padRows()[0].dispatchEvent(new Event('click'));
assert.deepEqual(padRows().map(n=>n['aria-pressed']),['true','false','false']);
assert.equal(descendants(card).find(n=>n['aria-label']==='Pad height (ft)').value,3);
assert.equal(grips().length,3);
const tick=()=>new Promise(r=>setTimeout(r,0));
const listPointer=(row,type,y,extra={})=>{const e=new Event(type,{cancelable:true});Object.assign(e,{button:0,pointerId:31,pointerType:'mouse',clientX:30,clientY:y,...extra});row.dispatchEvent(e);return e;};
const layoutRows=()=>padRows().map((row,i)=>{row.getBoundingClientRect=()=>({top:i*50,bottom:i*50+44,height:44});return row;});
let rows=layoutRows(),beforeList=ops.length;
listPointer(rows[0],'pointerdown',22);assert.equal(rows[0].capture,31);
listPointer(rows[0],'pointermove',149);
assert.equal(ops.length,beforeList,'moving previews only');
assert.equal(descendants(card).find(n=>n.className==='editor-pad-drop').hidden,false,'visible drop line');
listPointer(rows[0],'pointerup',149);await tick();
assert.deepEqual(ops.slice(beforeList),[{op:'reorder_pad',id:'distant',to:0}],'one drop, one history operation');
assert.deepEqual(plan.site.terraces.map(p=>p.id),['distant','pad','upper']);
rows=layoutRows();beforeList=ops.length;
listPointer(rows[0],'pointerdown',22);listPointer(rows[0],'pointermove',40);listPointer(rows[0],'pointerup',40);await tick();
assert.equal(ops.length,beforeList,'drop in place creates no history');
listPointer(rows[0],'pointerdown',22);listPointer(rows[0],'pointermove',149);listPointer(rows[0],'pointercancel',149);await tick();
assert.equal(ops.length,beforeList,'cancel creates no history');assert.equal(rows[0].capture,null);
// Reverse-direction drag and a synthesized post-drag click must also be safe.
listPointer(rows[2],'pointerdown',122);listPointer(rows[2],'pointermove',0);listPointer(rows[2],'pointerup',0);
rows[2].dispatchEvent(new Event('click'));await tick();
assert.deepEqual(ops.slice(beforeList),[{op:'reorder_pad',id:'distant',to:2}]);
assert.equal(padRows()[0]['aria-pressed'],'true','drag does not change the selected pad');
const rowKey=(row,key,altKey=true)=>{row.focus();const e=new Event('keydown',{cancelable:true});Object.assign(e,{key,altKey});row.dispatchEvent(e);return e;};
beforeList=ops.length;assert.equal(rowKey(padRows()[0],'ArrowDown').defaultPrevented,true);await tick();
assert.deepEqual(ops.slice(beforeList),[{op:'reorder_pad',id:'distant',to:1}]);
assert.equal(document.activeElement,padRows()[1],'keyboard focus follows the moved pad');
beforeList=ops.length;rowKey(padRows()[1],'ArrowUp');await tick();
assert.deepEqual(ops.slice(beforeList),[{op:'reorder_pad',id:'distant',to:2}]);
beforeList=ops.length;rowKey(padRows()[0],'ArrowUp');rowKey(padRows()[0],'ArrowDown',false);await tick();
assert.equal(ops.length,beforeList,'boundary and plain arrows create no history');
// Touch starts only on the grip, leaving row text available for scrolling.
rows=layoutRows();listPointer(rows[0],'pointerdown',22,{pointerType:'touch'});assert.equal(rows[0].capture,undefined);
const touchGrip=grips()[0];touchGrip.closest=selector=>selector==='.editor-pad-grip'?touchGrip:null;
const touchStart=new Event('pointerdown',{cancelable:true});Object.assign(touchStart,{button:0,pointerId:32,pointerType:'touch',clientX:30,clientY:22});
Object.defineProperty(touchStart,'target',{value:touchGrip});rows[0].dispatchEvent(touchStart);assert.equal(rows[0].capture,32);
listPointer(rows[0],'pointermove',149,{pointerId:32,pointerType:'touch'});
writable=false;terrain.refresh();assert.equal(rows[0].capture,null,'permission refresh cancels a drag');
assert.equal(grips().length,0);assert.equal(padRows().length,3);
rows=layoutRows();beforeList=ops.length;rowKey(rows[0],'ArrowDown');
listPointer(rows[0],'pointerdown',22);listPointer(rows[0],'pointermove',149);listPointer(rows[0],'pointerup',149);await tick();
assert.equal(ops.length,beforeList,'read-only list cannot reorder');
rows[2].dispatchEvent(new Event('click'));assert.equal(padRows()[2]['aria-pressed'],'true','read-only selection works');
writable=true;plan.site.terraces=savedPads;terrain.choose('terraces','pad');
console.log('Pads list labels, selection, pointer ordering, no-ops, cancel, keyboard focus and read-only passed');
writable=false;terrain.refresh();assert.equal(control('Send back').disabled,true);assert.equal(control('Bring forward').disabled,true);
const wallField=descendants(card).find(n=>n['aria-label']==='Edge 1 Wall');assert.ok(wallField.disabled);
const beforeWallReadOnly=ops.length;change('Edge 1 Wall','brick');await new Promise(r=>setTimeout(r,0));assert.equal(ops.length,beforeWallReadOnly);
const beforeReadOnly=ops.length;click('Send back');await new Promise(r=>setTimeout(r,0));assert.equal(ops.length,beforeReadOnly);
writable=true;terrain.refresh();click('Send back');await new Promise(r=>setTimeout(r,0));assert.equal(control('Send back').disabled,true);
terrain.choose('beds','bed');assert.equal(tools.selection().id,'bed');assert.equal(card.hidden,true,'yard selection uses the shared piece card');
fieldHost=document.getElementById('piece-card');change('Move east (ft)',3);await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'move_site_item',list:'beds',index:0,by:[3,0]});
assert.deepEqual(snapPadPoint([.4,12],plan),[0,12]);
writable=false;const count=ops.length;change('Move east (ft)',5);assert.equal(ops.length,count);writable=true;
plan.site.hardscape=[{id:'path',polygon:[[12,5],[14,5],[14,10],[12,10]]}];
plan.site.edges=[{id:'edge',points:[[28,5],[32,5]]}];
plan.site.pool={polygon:[[5,28],[10,28],[10,32],[5,32]]};
plan.site.fire_pit={at:[30,30],radius:2};plan.site.fence={polyline:[[35,5],[35,15]]};
for(const [kind,id,point] of [['beds','bed',[7,7]],['hardscape','path',[13,7]],['edges','edge',[30,5]],['pool','pool:0',[7,30]],['fire_pit','fire_pit:0',[30,30]],['fence','fence:0',[35,10]]]) {
  terrain.choose(kind,id);assert.equal(tools.selection().id,id);
  change('Move north (ft)',2);await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'move_site_item',list:kind,index:0,by:[0,2]});
  const p=event(point),picked=library.pickSite(p.clientX,p.clientY);assert.equal(picked?.kind,kind,kind+' footprint pick');
  const handle=tools.handles().find(h=>h.kind==='site_move');assert.ok(handle,kind+' move handle');
  const key=new Event('keydown');key.key='ArrowRight';document.dispatchEvent(key);await new Promise(r=>setTimeout(r,0));
  assert.equal(ops.at(-1).op,'move_site_item');assert.equal(ops.at(-1).list,kind);assert.deepEqual(ops.at(-1).by,[1,0]);
  const start=event(handle.at),canvas=view.renderer3.domElement;
  const pointer=(type,dx)=>{const e=new Event(type);Object.assign(e,{...start,clientX:start.clientX+dx});canvas.dispatchEvent(e);};
  pointer('pointerdown',0);pointer('pointermove',20);pointer('pointerup',20);await new Promise(r=>setTimeout(r,0));
  assert.equal(ops.at(-1).op,'move_site_item');assert.equal(ops.at(-1).list,kind);
  const del=new Event('keydown');del.key='Delete';document.dispatchEvent(del);await new Promise(r=>setTimeout(r,0));
  assert.equal(ops.at(-1).op,'delete_site_item');assert.equal(ops.at(-1).list,kind);assert.equal(tools.selection().id,null);
}
// Exercise the shared drawer's real pointer and keyboard entry points too.
terrain.show();click('Draw bed');const drawStart=ops.length,matStart=new THREE.MeshStandardMaterial().id;
for(const p of [[18,28],[22,28],[24,31],[22,34],[18,33]]){terrain.pointerDown({...event(p),shiftKey:true});terrain.pointerUp(event(p),false);}
terrain.pointerMove({...event([17,30]),shiftKey:true});
assert.ok(descendants(view.renderer3.domElement.parentElement).some(n=>n.textContent?.includes('sq ft')),'live area label');
assert.equal(ops.length,drawStart);assert.equal(new THREE.MeshStandardMaterial().id,matStart+1,'draw preview reuses its material');
let key=new Event('keydown');key.key='Enter';document.dispatchEvent(key);await new Promise(r=>setTimeout(r,0));
assert.equal(ops.length,drawStart+1);assert.equal(ops.at(-1).op,'add_site_shape');assert.equal(ops.at(-1).polygon.length,5);
terrain.show();click('Draw patio / hard surface');
for(const p of [[1,20],[4,24]]){terrain.pointerDown({...event(p),shiftKey:true});terrain.pointerUp(event(p),false);}
click('Rectangle');await new Promise(r=>setTimeout(r,0));assert.equal(ops.at(-1).polygon.length,4);assert.equal(ops.at(-1).list,'hardscape');
terrain.show();click('Paver path');
for(const p of [[18,20],[24,20],[24,24]]){terrain.pointerDown({...event(p),shiftKey:true});terrain.pointerUp(event(p),false);}
key=new Event('keydown');key.key='Backspace';document.dispatchEvent(key);click('Finish');await new Promise(r=>setTimeout(r,0));
assert.equal(ops.at(-1).points.length,2);assert.equal(ops.at(-1).width,3);assert.equal(ops.at(-1).corner,'rounded');
terrain.show();click('Draw bed');const cancelStart=ops.length;
terrain.pointerDown(event([20,20]));terrain.pointerUp(event([20,20]),false);
key=new Event('keydown');key.key='Escape';document.dispatchEvent(key);assert.equal(ops.length,cancelStart);assert.equal(card.hidden,true);
fieldHost=card;
for(const shape of ['round','square','rect','outline']) {
 terrain.show();click('Add fire pit');change('Shape',shape);
 const before=ops.length,materials=new THREE.MeshStandardMaterial().id;
 terrain.pointerMove({...event([20,20]),shiftKey:true});
 const points=shape==='outline'?[[17,17],[23,17],[23,21],[17,21]]:[[20,20]];
 for(const p of points){terrain.pointerDown({...event(p),shiftKey:true});assert.equal(ops.length,before);terrain.pointerUp(event(p),false);}
 assert.equal(new THREE.MeshStandardMaterial().id,materials+1,'pit placement/drawing uses the shared preview material');
 if(shape==='outline'){assert.equal(ops.length,before);key=new Event('keydown');key.key='Enter';document.dispatchEvent(key);}
 await new Promise(r=>setTimeout(r,0));assert.equal(ops.length,before+1);assert.equal(ops.at(-1).shape,shape);
 if(shape==='round')assert.equal(ops.at(-1).radius,2);
 if(shape==='square')assert.equal(ops.at(-1).side,4);
 if(shape==='rect'){assert.equal(ops.at(-1).width,4);assert.equal(ops.at(-1).depth,6);}
}
plan.site.fence.style='wood';terrain.show();click('Draw fence');const beforeFence=ops.length, fenceMaterial=new THREE.MeshStandardMaterial().id;
change('Height (ft)',7);change('Style','rail');
for(const p of [[28,20],[32,20],[32,24]]){terrain.pointerDown({...event(p),shiftKey:true});terrain.pointerUp(event(p),false);}
assert.equal(ops.length,beforeFence);assert.equal(new THREE.MeshStandardMaterial().id,fenceMaterial+1);
key=new Event('keydown');key.key='Enter';document.dispatchEvent(key);await new Promise(r=>setTimeout(r,0));
assert.equal(ops.length,beforeFence+1);assert.equal(ops.at(-1).list,'fence');assert.equal(ops.at(-1).polyline.length,3);assert.equal(ops.at(-1).height,7);assert.equal(ops.at(-1).style,'rail');
const host=new Element(), building={id:'b',base:0,foundation:{mode:'fixed',offset_ft:0,thickness_ft:1}};
let preview;
foundationShelf(host,building,{getPlan:()=>({buildings:[building]}),canEdit:()=>true,queue:fn=>Promise.resolve().then(fn),op,report:error=>{throw error;},preview:async plan=>{preview=plan;}});
const mode=descendants(host).find(n=>n['aria-label']==='Foundation mode');mode.value='auto';mode.dispatchEvent(new Event('change'));
await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.at(-1),{op:'set_foundation',building:'b',foundation:{mode:'auto',offset_ft:0,thickness_ft:1}});
const offset=descendants(host).find(n=>n['aria-label']==='Offset (ft)');offset.value='2';offset.dispatchEvent(new Event('input'));
await new Promise(r=>setTimeout(r,210));assert.equal(preview.buildings[0].foundation.offset_ft,2,'foundation input runs a live preview without mutating the model');assert.equal(building.foundation.offset_ft,0);
abort.abort();view.dispose();console.log('Terrain editor draw, edge, nudge, vertex drag, yard move, read-only and foundation fields passed');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_ground_tools_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=300)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
