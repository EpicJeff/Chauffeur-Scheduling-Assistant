"""Real CPU camera rays, shelf events and history for authored yard shapes."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from test_twin_drag_js import DRIVER as BASE, ROOT

DRIVER = BASE.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE=await import(three);
const {createHandles}=await import(file('static/twin/editor/handles.js'));
const {createHistory}=await import(file('static/twin/editor/history.js'));
const {siteRecord}=await import(file('static/twin/objects.js'));
const shapes=await import(file('static/twin/editor/site_shapes.js'));
const vertices=await import(file('static/twin/editor/polygon_handles.js'));
const {drawSiteShapeShelf}=await import(file('static/twin/editor/site_shape_shelf.js'));
const {drawObjectShelf}=await import(file('static/twin/editor/object_shelf.js'));
const {mountTwin}=await import(file('static/twin/twin_view.js'));
window.twinObjectSchema=JSON.parse(readFileSync(root+'/static/twin/object_schema.json'));
const descendants=n=>n.children.flatMap(c=>[c,...descendants(c)]), nodes=new Map();
document.getElementById=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
document.querySelector=()=>null;
const plan={buildings:[],materials:{},site:{beds:[{id:'bed',polygon:[[0,0],[8,0],[8,4],[0,4]]}],hardscape:[{id:'patio',polygon:[[0,0],[8,0],[8,4],[0,4]]}],
 pool:{polygon:[[0,0],[8,0],[8,4],[0,4]],depth:5,coping:1},fire_pit:{at:[4,2],radius:2},fence:{polyline:[[0,0],[8,0]],height:6},planting:[],furniture:[]}};
let source=structuredClone(plan),selected={kind:'beds',id:'bed',building:null},round=1,commits=0,writable=true;
const abort=new AbortController(),snapshots=new Map([[1,structuredClone(source)]]),ops=[];
let history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>writable,refresh:async()=>{},signal:abort.signal});
const commit=operation=>history.perform(async()=>{
 commits++;ops.push(operation);const value=source.site[operation.list],p=Array.isArray(value)?value[operation.index]:value;
 if(operation.op==='set_object')Object.assign(p,operation.properties);else Object.assign(p,Object.fromEntries(Object.entries(operation).filter(([k])=>!['op','list','index'].includes(k))));
 snapshots.set(++round,structuredClone(source));
});
const view=await mountTwin(new Element(),{plan:source,kit,tier:'low',preserveCamera:true});
view.camera.position.set(4*.3048,25, -2*.3048+.001);view.camera.lookAt(4*.3048,0,-2*.3048);view.camera.updateMatrixWorld(true);
const handles=createHandles({view,getPlan:()=>source,getSelection:()=>selected,canEdit:()=>writable,drag:{},onCommit:commit,signal:abort.signal});
const event=at=>{const p=new THREE.Vector3(at[0]*.3048,(at[2]||0)*.3048,-at[1]*.3048).project(view.camera);return {clientX:(p.x+1)*720,clientY:(1-p.y)*450};};
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} near ${b}`);
const gesture=async(kind,target,extra={})=>{const h=handles.handles().find(h=>h.kind===kind);assert.ok(h,kind);const before=commits;assert.ok(handles.begin({...event(h.at),...extra}));for(let i=0;i<4;i++)handles.update({...event(target),...extra});assert.equal(commits,before);await handles.finish();assert.equal(commits,before+1);};
await gesture('site_rotate',[4,12,0]);
assert.deepEqual(source.site.beds[0].polygon,[[6,-2],[6,6],[2,6],[2,-2]]);assert.equal(source.site.beds[0].rotation,90);
assert.deepEqual(shapes.shapeCentre(source.site.beds[0]),[4,2]);
console.log('ok bed 90 degree centroid rotation has exact corners, one release and no intermediate ops');
// No THREE object or material may be allocated by a handle drag. UUIDs are
// random; material IDs are monotonic and expose even discarded allocations.
const materialBefore=new THREE.MeshStandardMaterial().id;
selected={kind:'hardscape',id:'patio',building:null};
let h=handles.handles().find(h=>h.kind==='site_scale');const c=[4,2];
await gesture('site_scale',[c[0]+(h.at[0]-c[0])*1.5,c[1]+(h.at[1]-c[1])*1.5,0]);
assert.deepEqual(source.site.hardscape[0].polygon,[[-2,-1],[10,-1],[10,5],[-2,5]]);
assert.equal(new THREE.MeshStandardMaterial().id,materialBefore+1,'no material created while dragging');
console.log('ok patio 150 percent, centroid unchanged, no drag material allocations');
const record=()=>siteRecord(source,selected.id), shelf=new Element();
let pending=Promise.resolve();const queue=fn=>pending=pending.then(fn);
const draw=()=>{shelf.replaceChildren();drawSiteShapeShelf(shelf,record(),{canEdit:()=>writable,queue,op:commit,report:e=>{throw e;},getRecord:record});};
const change=async(label,value)=>{const input=descendants(shelf).find(n=>n['aria-label']===label);assert.ok(input,label);input.value=String(value);input.dispatchEvent(new Event('change'));await pending;await new Promise(r=>setTimeout(r,0));draw();};
draw();await change('X scale (%)',200);assert.deepEqual(shapes.shapeSize(record().piece),[24,6]);
await change('Y scale (%)',50);assert.deepEqual(shapes.shapeSize(record().piece),[24,3]);
await change('Width (ft)',12);await change('Depth (ft)',6);assert.deepEqual(shapes.shapeSize(record().piece),[12,6]);
await change('Centre X (ft)',10);await change('Centre Y (ft)',20);assert.deepEqual(shapes.shapeCentre(record().piece),[10,20]);
await change('Angle (degrees)',45);assert.equal(record().piece.rotation,45);
await change('Angle (degrees)',0);assert.equal(record().piece.rotation,0);near(shapes.shapeSize(record().piece)[0],12);
console.log('ok shelf X/Y scale, bounding dimensions, centre and angle round trip');
selected={kind:'pool',id:'pool:0',building:null};draw();await change('Pool depth (ft)',6);await change('Coping (ft)',0);assert.equal(source.site.pool.depth,6);assert.equal(source.site.pool.coping,0);
selected={kind:'fire_pit',id:'fire_pit:0',building:null};await gesture('site_radius',[7,2,0]);near(source.site.fire_pit.radius,3);draw();await change('Radius (ft)',4);near(source.site.fire_pit.radius,4);
await gesture('site_rotate',[4,8,0]);assert.equal(source.site.fire_pit.rotation,90);draw();await change('Angle (degrees)',45);assert.equal(source.site.fire_pit.rotation,45);
source.site.fire_pit=[source.site.fire_pit];
for(const shape of ['square','rect','outline']) {
 const pit={id:'pit-'+shape,shape,polygon:[[0,0],[8,0],[8,6],[0,6]]};source.site.fire_pit.push(pit);selected={kind:'fire_pit',id:pit.id,building:null};
 assert.equal(handles.handles().some(h=>h.kind==='site_radius'),false);assert.ok(handles.handles().some(h=>h.kind==='site_rotate'));
 await gesture('site_vertex',[-1,1,0]);h=handles.handles().find(h=>h.kind==='site_insert');assert.ok(handles.begin(event(h.at)));await handles.finish();assert.equal(record().piece.polygon.length,5);
 h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();assert.equal(record().piece.polygon.length,4);
 draw();await change('Angle (degrees)',30);assert.equal(record().piece.rotation,30);
}
console.log('ok round pit radius/turn and polygon pit corners, insert/remove and turn through history');
selected={kind:'fence',id:'fence:0',building:null};
await gesture('site_vertex',[0,2,0]);assert.deepEqual(source.site.fence.polyline[0],[0,2]);
h=handles.handles().find(h=>h.kind==='site_insert');assert.ok(handles.begin(event(h.at)));await handles.finish();assert.equal(source.site.fence.polyline.length,3);
h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();assert.equal(source.site.fence.polyline.length,2);
draw();await change('Height (ft)',8);assert.equal(source.site.fence.height,8);
console.log('ok pool fields, radius handle and shelf, fence point insert/drag/remove and height');
source.site.hardscape.push({id:'walk',kind:'path',points:[[0,0],[8,0],[8,8]],width:3,material:'paving'});
selected={kind:'hardscape',id:'walk',building:null};await gesture('site_vertex',[-1,1,0]);
h=handles.handles().find(h=>h.kind==='site_insert');assert.ok(handles.begin(event(h.at)));await handles.finish();assert.equal(record().piece.points.length,4);
for(let i=0;i<2;i++){h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();}
assert.equal(record().piece.points.length,2);const pathMinimum=commits;
h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();assert.equal(commits,pathMinimum);
draw();await change('Width (ft)',4);assert.equal(record().piece.width,4);
console.log('ok path centre-line drag, midpoint insertion, removal to two points and shelf width through history');
selected={kind:'beds',id:'bed',building:null};
h=handles.handles().find(h=>h.kind==='site_insert');assert.ok(handles.begin(event(h.at)));await handles.finish();assert.equal(record().piece.polygon.length,5);
for(let i=0;i<2;i++){h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();}
const beforeMin=commits;h=handles.handles().find(h=>h.kind==='site_vertex');assert.ok(handles.begin({...event(h.at),altKey:true}));await handles.finish();assert.equal(commits,beforeMin);assert.equal(record().piece.polygon.length,3);
assert.equal(vertices.editVertex([[0,0],[1,0],[0,1]],{index:0},[0,0],{remove:true}).length,3);
h=handles.handles().find(h=>h.kind==='site_scale');assert.ok(handles.begin(event(h.at)));handles.update(event([20,20,0]));await handles.finish(true);assert.equal(commits,beforeMin);
const alerts=[];window.showGlobalAlert=t=>alerts.push(t);
globalThis.fetch=async(input,init)=>{const body=JSON.parse(init.body);source=structuredClone(snapshots.get(body.round));snapshots.set(++round,structuredClone(source));return new Response(JSON.stringify({round}),{status:200});};
const beforeUndo=structuredClone(source);document.getElementById('rail-undo').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,0));assert.notDeepEqual(source,beforeUndo);
document.getElementById('rail-redo').dispatchEvent(new Event('click'));await new Promise(r=>setTimeout(r,0));assert.deepEqual(source,beforeUndo);assert.equal(alerts.length,0);
console.log('ok minimum three corners, cancelled gesture, real history undo and redo');
// Every known plant/furniture record uses the same schema and handles,
// including imported objects and alternate object kinds on either list.
for(const collection of ['planting','furniture'])for(const kind of ['tree','shrub','chair','imported',...Object.keys(window.twinObjectSchema.kinds)]){
 const p={id:collection+'-'+kind,at:[4,2],kind,...(kind==='imported'?{asset:'import-fixture'}:kind in window.twinObjectSchema.kinds?{object_kind:kind}:{})};source.site[collection]=[p];selected={kind:collection,id:p.id,building:null};
 assert.ok(handles.handles().some(h=>h.kind==='object_scale'),collection+kind);assert.ok(handles.handles().some(h=>h.kind==='object_rotate'),collection+kind);
 const host=new Element();drawObjectShelf(host,siteRecord(source,p.id),{canEdit:()=>true,queue,op:commit,report:e=>{throw e;}});
 assert.ok(descendants(host).some(n=>n['aria-label']==='Scale (factor)'));assert.ok(descendants(host).some(n=>n['aria-label']==='Yaw (degrees)'));
 for(const [label,value] of [['Scale (factor)',1.3],['Yaw (degrees)',30]]){const input=descendants(host).find(n=>n['aria-label']===label);input.value=String(value);input.dispatchEvent(new Event('change'));await pending;}
 assert.equal(p.scale,1.3,collection+kind+' shelf size saves');assert.equal(p.rotation,30,collection+kind+' shelf turn saves');
}
console.log('ok all yard tree, shrub, chair, import and schema kinds expose size and turn');
writable=false;assert.equal(handles.handles().length,0);writable=true;abort.abort();
// Exercise scene_tools too: its click/release cancellation and Shift room
// selection precede handles, so direct handle tests alone cannot prove these.
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
Element.prototype.getAttribute=function(k){return this[k];};Element.prototype.closest=()=>null;
Element.prototype.querySelectorAll=function(selector){return descendants(this).filter(n=>selector==='button'?n.tag==='button':false);};
Element.prototype.setPointerCapture=function(id){this.capture=id;};Element.prototype.hasPointerCapture=function(id){return this.capture===id;};Element.prototype.releasePointerCapture=function(){this.capture=null;};
document.querySelectorAll=()=>[];
const uiAbort=new AbortController(),tools=createSceneTools({view,getPlan:()=>source,getModel:()=>source,getKit:()=>kit,getSheets:()=>({}),op:commit,edit:commit,
 panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:uiAbort.signal});
tools.select({kind:'hardscape',id:'patio',building:null});
const pointer=(type,at,extra={})=>{const e=new Event(type);Object.assign(e,{...event(at),button:0,pointerId:77,...extra});(type==='pointerup'?window:view.renderer3.domElement).dispatchEvent(e);};
h=tools.handles().find(h=>h.kind==='site_insert');const cornersBefore=source.site.hardscape[0].polygon.length;
pointer('pointerdown',h.at);pointer('pointerup',h.at);await new Promise(r=>setTimeout(r,0));assert.equal(source.site.hardscape[0].polygon.length,cornersBefore+1,'real click inserts on release');
tools.refreshCard();h=tools.handles().find(h=>h.kind==='site_vertex');pointer('pointerdown',h.at,{altKey:true});pointer('pointerup',h.at,{altKey:true});await new Promise(r=>setTimeout(r,0));assert.equal(source.site.hardscape[0].polygon.length,cornersBefore,'real Alt-click removes on release');
h=tools.handles().find(h=>h.kind==='site_rotate');const origin=shapes.shapeCentre(source.site.hardscape[0]),r=h.at[0]-origin[0],angle=22*Math.PI/180;
pointer('pointerdown',h.at,{shiftKey:true});pointer('pointermove',[origin[0]+r*Math.cos(angle),origin[1]+r*Math.sin(angle),h.at[2]],{shiftKey:true});pointer('pointerup',[origin[0]+r*Math.cos(angle),origin[1]+r*Math.sin(angle),h.at[2]],{shiftKey:true});await new Promise(r=>setTimeout(r,0));near(source.site.hardscape[0].rotation,22);
assert.equal(view.controls.enabled,true);
// Match the live patio, camera and twelve browser move events. The real
// scene-tools router owns the real handle module, including release routing.
source=structuredClone(plan);source.site.hardscape=[{id:'patio',polygon:[[12,117],[28,117],[28,133],[12,133]]}];
history=createHistory({getRound:()=>round,getBuild:()=>null,canEdit:()=>writable,refresh:async()=>{},signal:uiAbort.signal});snapshots.set(round,structuredClone(source));
view.setCameraState({position:[20*.3048,80*.3048,-124.999*.3048],target:[20*.3048,0,-125*.3048]});
tools.select({kind:'hardscape',id:'patio',building:null});
const states=[structuredClone(source)],tick=()=>new Promise(r=>setTimeout(r,0));
async function liveNoChange(kind,target){
 const start=tools.handles().find(h=>h.kind===kind).at,before=commits,original=structuredClone(source);
 pointer('pointerdown',start);pointer('pointermove',target(start));pointer('pointermove',start);
 pointer('pointerup',start);pointer('click',start);await tick();
 assert.equal(commits,before,kind+' no-change release records no history');assert.deepEqual(source,original);
}
await liveNoChange('site_rotate',start=>[start[0],start[1]+.3,start[2]]);
await liveNoChange('site_move',start=>[start[0]+1,start[1],start[2]]);
await liveNoChange('site_scale',start=>[start[0]+1,start[1]+1,start[2]]);
async function historyLength(expected){
 // Exhaust each stack through its actual buttons: exactly N state-changing
 // reverts, then a disabled Undo, proves the history length without mocks.
 for(let i=expected-1;i>=0;i--){document.getElementById('rail-undo').dispatchEvent(new Event('click'));await tick();assert.deepEqual(source,states[i],'one undo per gesture');}
 assert.equal(document.getElementById('rail-undo').disabled,true,'history length is exactly '+expected);
 for(let i=1;i<=expected;i++){document.getElementById('rail-redo').dispatchEvent(new Event('click'));await tick();assert.deepEqual(source,states[i],'one redo per gesture');}
 assert.equal(document.getElementById('rail-redo').disabled,true);
}
async function liveGesture(kind,target){
 const start=tools.handles().find(h=>h.kind===kind).at,end=target(start),before=commits;
 pointer('pointermove',start);
 pointer('pointerdown',start);
 for(let i=1;i<=12;i++)pointer('pointermove',start.map((v,j)=>v+(end[j]-v)*i/12));
 pointer('pointerup',end);
 // The window capture listener runs before the same release reaches document
 // and canvas; lostpointercapture and click must not save a second time.
 for(const surface of [document,view.renderer3.domElement]){const e=new Event('pointerup');Object.assign(e,{...event(end),button:0,pointerId:77});surface.dispatchEvent(e);}
 pointer('lostpointercapture',end);pointer('click',end);await tick();
 assert.equal(commits,before+1,kind+' commits exactly once');
 assert.notDeepEqual(source,states.at(-1),kind+' changes the authored shape');states.push(structuredClone(source));
 await historyLength(states.length-1);
}
await liveGesture('site_rotate',start=>{const radius=start[0]-20;return [20+radius/Math.SQRT2,125+radius/Math.SQRT2,start[2]];});
await liveGesture('site_scale',start=>[20+(start[0]-20)*1.2,125+(start[1]-125)*1.2,start[2]]);
await liveGesture('site_vertex',start=>[start[0]+1,start[1],start[2]]);
await liveNoChange('site_vertex',start=>[start[0]+1,start[1],start[2]]);
for(let i=2;i>=0;i--){document.getElementById('rail-undo').dispatchEvent(new Event('click'));await tick();assert.deepEqual(source,states[i],'one undo per gesture');}
assert.equal(document.getElementById('rail-undo').disabled,true,'history has exactly three steps');
assert.equal(alerts.length,0,'own undo/redo rounds are never treated as outside edits');
console.log('ok browser-style window release and click: rotate, scale and one-foot corner each add one history step; no-change releases add none; three undos and redos');
history.clear();
await commit(shapes.shapeOperation(siteRecord(source,'patio'),shapes.transformShape(source.site.hardscape[0],{rotation:15})));
source.site.hardscape[0].name='Another person changed this';snapshots.set(++round,structuredClone(source));
await commit(shapes.shapeOperation(siteRecord(source,'patio'),shapes.transformShape(source.site.hardscape[0],{rotation:30})));
document.getElementById('rail-undo').dispatchEvent(new Event('click'));await tick();
const outsideState=structuredClone(source),outsideRound=round;
document.getElementById('rail-undo').dispatchEvent(new Event('click'));await tick();
assert.deepEqual(source,outsideState);assert.equal(round,outsideRound);assert.equal(alerts.length,1);assert.match(alerts[0],/Something else changed/);
console.log('ok an outside edit between two own gestures still blocks undo across that boundary');
uiAbort.abort();view.dispose();
console.log('ok actual scene-tools midpoint click, Alt-click, Shift free rotation and camera restoration');
"""


def run():
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='chauffeur_shapes_js_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': {}, 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=90)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
