"""CPU event-path checks for the library; Chromium remains the controller's gate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
os.environ.setdefault('CHAUFFEUR_DATA_DIR', tempfile.mkdtemp(prefix='chauffeur_library_ui_'))
os.environ.pop('HA_BASE_URL', None)
from test_twin_drag_js import DRIVER as DRAG_DRIVER
from twin_editor_dom import PRELUDE, run_node

REGRESSIONS = PRELUDE + r"""
const {surfaceOperation}=await import(file('static/twin/editor/library.js'));
await test('surface_operation_id_only',async()=>{
 const surface={building:{id:'house'},piece:{id:'wall'},kind:'wall',side:'left',room:{id:'room'},role:'siding',level:'L1'};
 for(const scope of ['face','room','level','building']){
  const operation=surfaceOperation(surface,scope,{id:'material-household',color:'#789abc',thumbnail_url:'stone.png'});
  assert.deepEqual(operation.material,{id:'material-household'},scope+' ordinary pick must not copy the swatch');
 }
});
finish();
"""

SELECTIONS = PRELUDE + r"""
const THREE=await import(three),{createLibrary}=await import(file('static/twin/editor/library.js'));
const {createSlotRow}=await import(file('static/twin/editor/slot_row.js')).catch(()=>({}));
const panel=document.getElementById('library-panel'),grid=document.getElementById('library-entries'),bar=document.getElementById('library-actions');
panel.append(grid,bar,document.getElementById('library-search'));
for(const name of ['materials','items']){const b=document.createElement('button');b.dataset.libraryTab=name;panel.append(b);}
const canvas=document.createElement('canvas');document.getElementById('editor-scene').append(canvas);
const view={scene:new THREE.Scene(),renderer3:{domElement:canvas},camera:new THREE.PerspectiveCamera(),controls:new EventTarget(),pick:()=>null};
let dockTab='scene';const dockListeners=[];const dock={show:tab=>{dockTab=tab;dockListeners.forEach(fn=>fn(tab));},current:()=>dockTab,onShow:fn=>{dockListeners.push(fn);return()=>{};}};
let catalogue=structuredClone(input.catalogue),materialRows=structuredClone(input.materials),requests=[];
let detailReads=0,detailGate=null;
// Thumbnail rendering is external to selection. Keep the real catalogue's ids/names/kinds.
for(const row of [...catalogue.items,...catalogue.imports,...materialRows])row.thumbnail_url='/fixture.png';
const imported={id:'import-selection',kind:'door',name:'Front door',thumbnail_url:'/door.png',lods:[{name:'medium.glb'},{name:'low.glb'}]};catalogue.imports.push(imported);
catalogue.items.push({id:'manifest-door',kind:'furniture',name:'Manifest door',thumbnail_url:'/door.png'});
window.twinManifest={'manifest-door':{kind:'model',object_kind:'door'}};
globalThis.fetch=async(url,options={})=>{
 requests.push([url,options]);let result;
 if(url.endsWith('/materials'))result={materials:materialRows};
 else if(url.endsWith('/materials/material-reveal')){
  const ordinal=++detailReads;await detailGate;if(ordinal===1)await new Promise(r=>setTimeout(r,50));
  result={id:'material-reveal',revision:1,params:{},maps:{}};
 }
 else if(url.endsWith('/library'))result=catalogue;
 else if(url.endsWith('/imports'))result=[];
 else if(url.endsWith('/imports/'+imported.id)){
  if(options.method==='PATCH')Object.assign(imported,JSON.parse(options.body));
  if(options.method==='DELETE')catalogue.imports=catalogue.imports.filter(e=>e.id!==imported.id);
  result=imported;
 } else if(url.endsWith('/import-settings'))result={limit_mb:50};
 else throw Error('unexpected '+url);
 return new Response(JSON.stringify(result));
};
const abort=new AbortController(),sceneSelection={kind:'wall',id:'kept'},ops=[],menus=[];
const library=createLibrary({view,kit:input.kit,getPlan:()=>input.household,tools:{selection:()=>sceneSelection},op:async o=>ops.push(o),canEdit:()=>true,signal:abort.signal,dock,
 createMenu:options=>({open:(event,target)=>menus.push(options.items(target))})});
const wait=async()=>{await new Promise(r=>setTimeout(r,25));};
dock.show('library');await wait();
const tile=id=>grid.querySelector(`[data-material="${id}"], [data-item="${id}"]`);
const first=materialRows[0],last=materialRows.at(-1),byText=text=>bar.querySelectorAll('button,a').find(n=>n.textContent===text);
await test('tile clicks select, toggle and never change the scene or apply',async()=>{
 assert.equal(typeof library.selected,'function');
 await fire(tile(first.id),'pointerdown',{button:0,pointerId:1,clientX:10,clientY:10});
 await fire(document,'pointerup',{pointerId:1,clientX:10,clientY:10});await click(tile(first.id));
 assert.equal(document.activeElement,tile(first.id),'pointer selection keeps focus in the Library for Esc');
 assert.equal(library.selected().kind,'material');assert.equal(library.selected().id,first.id);assert.equal(library.selected().thumb,'/fixture.png');
 assert.equal(tile(first.id).getAttribute('aria-pressed'),'true');assert.equal(ops.length,0);assert.equal(sceneSelection.id,'kept');
 await click(tile(last.id));assert.equal(tile(first.id).getAttribute('aria-pressed'),'false');
 await click(tile(last.id));assert.equal(library.selected(),null);
});
await test('selection survives subtab, dock, search, real catalogue reread and scene refresh',async()=>{
 library.select({...first,kind:'material'});const changes=[];const off=library.onSelect(e=>changes.push(e));
 await click(panel.querySelector('[data-library-tab="items"]'));dock.show('scene');dock.show('library');await wait();assert.equal(library.selected().id,first.id);
 await click(panel.querySelector('[data-library-tab="materials"]'));
 document.getElementById('library-search').value='no-match';await fire(document.getElementById('library-search'),'input');
 assert.equal(library.selected().id,first.id);document.getElementById('library-search').value='';
 materialRows=materialRows.map(e=>({...e,name:e.id===first.id?'Updated family finish':e.name}));
 await fire(document,'chf-materials-changed');await wait();library.refresh();
 assert.equal(library.selected().name,'Updated family finish');assert.equal(tile(first.id).getAttribute('aria-pressed'),'true');
 assert.ok(changes.some(e=>e?.name==='Updated family finish'));off();
 dock.show('scene');materialRows=materialRows.filter(e=>e.id!==first.id);await fire(window,'focus');await wait();assert.equal(library.selected(),null);
 assert.equal(dockTab,'scene','external deletion reconciles selection without opening Library');dock.show('library');await wait();
});
await test('action bar and tile context menu keep the material link and import calls',async()=>{
 const asset=materialRows.at(-1);await click(tile(asset.id));
 assert.equal(grid.querySelector('a'),null);const edit=byText('Edit in Library');assert.ok(edit.href.endsWith('material='+encodeURIComponent(asset.id)));
 assert.equal(edit.target,'_blank');assert.equal(edit.rel,'noopener');
 await fire(tile(asset.id),'contextmenu');assert.deepEqual(menus.at(-1).map(e=>e.label),['Edit in Library']);
 await click(panel.querySelector('[data-library-tab="items"]'));await click(tile(imported.id));
 assert.equal(grid.querySelectorAll('button').filter(n=>/^Rename |^Delete /.test(n.textContent)).length,0);
 const focusedRename=byText('Rename Front door');focusedRename.focus();await fire(window,'focus');await wait();
 assert.ok(focusedRename.isConnected,'catalogue/background updates keep the action controls attached');
 assert.equal(document.activeElement,focusedRename);
 window.promptInput=async()=> 'Renamed door';await click(byText('Rename Front door'));
 assert.equal(library.selected().name,'Renamed door');assert.ok(byText('Delete Renamed door'));
 assert.equal(JSON.parse(requests.find(([url,o])=>o.method==='PATCH')[1].body).name,'Renamed door');
 imported.kind='window';await fire(window,'focus');await wait();
 assert.equal(library.selected()?.kind,'window','selection follows catalogue metadata by id when an import changes kind');
 await fire(tile(imported.id),'contextmenu');assert.deepEqual(menus.at(-1).map(e=>e.label),['Rename Renamed door','Delete Renamed door']);
 let asked=0;window.promptConfirm=async()=>{asked++;return false;};await click(byText('Delete Renamed door'));assert.ok(tile(imported.id));
 window.promptConfirm=async()=>{asked++;return true;};await click(byText('Delete Renamed door'));
 assert.equal(asked,2);assert.equal(tile(imported.id),null);assert.equal(library.selected(),null);
 assert.equal(requests.filter(([url,o])=>o.method==='DELETE').length,1);
});
await test('reveal clears search, switches dock and subtab, scrolls and flashes without selecting',async()=>{
 library.select(null);document.getElementById('library-search').value='no-match';dock.show('scene');
 let scrolled=[];Element.prototype.scrollIntoView=function(){scrolled.push(this);};
 await library.reveal('material',last.id);assert.equal(dockTab,'library');assert.ok(scrolled.includes(tile(last.id)));
 assert.ok(tile(last.id).classList.contains('library-revealed'));assert.equal(library.selected(),null);
 const revealed=tile(last.id);await wait();assert.equal(tile(last.id),revealed,'late catalogue work does not replace the revealed tile');
 const item=catalogue.items.at(-1);await library.reveal(item.kind,item.id);assert.ok(scrolled.includes(tile(item.id)));assert.equal(library.selected(),null);
});
await test('pick is reveal only, including the inherited current material',async()=>{
 const current=materialRows.at(-1);input.household.buildings[0].materials={roof:{id:current.id}};
 const surface={building:input.household.buildings[0],piece:{id:'pick-roof',level:'ground'},kind:'roof',role:'roof'};
 library.select(null);dock.show('scene');const before=ops.length;
 await library.pick(surface);assert.equal(dockTab,'library');
 assert.ok(tile(current.id).classList.contains('library-revealed'));
 await click(tile(current.id));assert.equal(library.selected().id,current.id);assert.equal(ops.length,before);
 assert.equal(document.querySelector('#material-chooser'),null,'pick never arms tile application');
 library.select(null);
});
await test('manifest model classification reaches actual tile selections without changing placement kind',async()=>{
 await library.reveal('door','manifest-door');await click(tile('manifest-door'));
 assert.equal(library.selected().kind,'furniture');assert.equal(library.selected().object_kind,'door');
 const row=createSlotRow({label:'Model',accepts:e=>e.kind==='door'||e.object_kind==='door',current:()=>null,apply(){},clear(){},library});
 assert.equal(row.element.querySelector('[data-slot-use]').disabled,false);row.dispose();library.select(null);
});
await test('Esc clears only a focused Library selection; clear action works',async()=>{
 await library.reveal('material',last.id);await click(tile(last.id));canvas.focus();await fire(document,'keydown',{key:'Escape'});assert.ok(library.selected());
 tile(last.id).focus();await fire(document,'keydown',{key:'Escape'});assert.equal(library.selected(),null);
 await click(tile(last.id));await click(byText('Clear selection'));assert.equal(library.selected(),null);
});
await test('real tile pointer drags assign slots without changing Library selection',async()=>{
 assert.equal(typeof createSlotRow,'function');library.select({...materialRows[0],kind:'material'});
 const before=library.selected().id,applied=[];
 const row=createSlotRow({label:'Floor',accepts:e=>e.kind==='material',current:()=>null,apply:e=>applied.push(e),clear(){},library});document.body.append(row.element);
 document.elementFromPoint=()=>row.element.querySelector('[data-slot-use]');
 await fire(tile(last.id),'pointerdown',{button:0,pointerId:2,clientX:10,clientY:10});
 await fire(document,'pointermove',{pointerId:2,clientX:200,clientY:200});assert.ok(row.element.classList.contains('editor-slot-dragover'));
 await fire(document,'pointerup',{pointerId:2,clientX:200,clientY:200});await fire(tile(last.id),'click',{detail:1});
 assert.equal(applied.at(-1).id,last.id);assert.equal(library.selected().id,before);assert.equal(ops.length,0);
 await fire(tile(last.id),'pointerdown',{button:0,pointerId:3,clientX:10,clientY:10});
 await fire(document,'pointermove',{pointerId:3,clientX:200,clientY:200});await fire(document,'pointercancel',{pointerId:3});
 assert.ok(!row.element.classList.contains('editor-slot-dragover'));row.dispose();
});
await test('cold reveal shares the dock catalogue read and flashes the final tile',async()=>{
 library.select(null);dock.show('scene');
 materialRows.push({id:'material-reveal',name:'Reveal finish',source:'user',revision:1,thumbnail_url:'/fixture.png'});
 await fire(document,'chf-materials-changed');
 let release;detailGate=new Promise(resolve=>release=resolve);
 const pending=library.reveal('material','material-reveal');
 for(let i=0;i<30&&!detailReads;i++)await wait();await wait();
 const reads=detailReads;release();await pending;const revealed=tile('material-reveal');await new Promise(r=>setTimeout(r,80));
 assert.equal(reads,1,'dock open and reveal share one household detail fetch');
 assert.equal(tile('material-reveal'),revealed);assert.ok(revealed.classList.contains('library-revealed'));
});
abort.abort();finish();
"""

DRIVER = DRAG_DRIVER.split('const {createDrag, piecesOnMovedJoints}')[0] + r"""
const THREE = await import(three);
const {mountTwin} = await import(file('static/twin/twin_view.js'));
const {createSceneTools} = await import(file('static/twin/editor/scene_tools.js'));
const {createLibrary, materialLines, surfaceOperation, itemOperation, wallFace} = await import(file('static/twin/editor/library.js'));
const nodes = new Map(), doc = new Element();
const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
Element.prototype.getAttribute = function(k) {return this[k];};
Element.prototype.querySelectorAll = function(selector) {
  return descendants(this).filter(n => selector === 'button' ? n.tag === 'button' : selector === '[data-library-tab]' ? !!n.dataset.libraryTab : false);
};
Element.prototype.querySelector = function(selector) {return this.querySelectorAll(selector)[0] || null;};
Element.prototype.contains = function(node) {return node === this || descendants(this).includes(node);};
Element.prototype.focus = function() {};
Element.prototype.scrollIntoView = function() {};
Element.prototype.setPointerCapture = function(id) {this.capture = id;};
Element.prototype.hasPointerCapture = function(id) {return this.capture === id;};
Element.prototype.releasePointerCapture = function() {this.capture = null;};
Element.prototype.toDataURL = () => 'data:image/png;base64,preview';
Element.prototype.remove = function() {
  if (this.parentElement) this.parentElement.children=this.parentElement.children.filter(n=>n!==this);
  this.parentElement=null;
};
doc.createElement = tag => {const node = new Element(); node.tag = tag; return node;};
doc.createElementNS = (_namespace, tag) => doc.createElement(tag);
doc.createTextNode = text => {const node = new Element(); node.textContent = text; return node;};
Element.prototype.click = function() {this.dispatchEvent(new Event('click'));};
doc.getElementById = id => {if (!nodes.has(id)) nodes.set(id, new Element()); return nodes.get(id);};
doc.querySelector = () => null; doc.querySelectorAll = () => []; globalThis.document = doc;
window.innerWidth = 1440; window.innerHeight = 900; window.showGlobalAlert = text => {throw Error(text);};
window.promptConfirm = async () => true;
const panel = doc.getElementById('library-panel'); panel.hidden = true;
for (const name of ['materials','items']) {const tab=doc.createElement('button');tab.dataset.libraryTab=name;panel.append(tab);}
panel.append(doc.getElementById('library-entries'),doc.getElementById('library-actions'));
const actionBar=()=>descendants(doc.getElementById('library-actions'));
const b = flat.buildings.find(b => b.id === 'pool-house'), room = b.rooms.find(r => r.name === 'Pool Lounge');
const front = b.walls.find(w => w.id === 'wall:44b42dc9c06144adbeaeb88ce33b0430');
const finish = {id:'red_brick_03',name:'Red brick 03',color:'#ad5946',thumbnail_url:'/ingress/test/stone.png'};
const latticeFinish={id:'lattice',name:'Lattice',color:kit.materials.lattice.color};
const previewMaterials=[],renderPreview=globalThis.Renderer.prototype.render;
globalThis.Renderer.prototype.render=function(scene){
 scene.traverse(o=>{if(o.geometry?.type==='SphereGeometry')previewMaterials.push(o.material);});
 return renderPreview.call(this,scene);
};
const chair = {id:'mid_century_lounge_chair',name:'Lounge chair',kind:'furniture'};
const imported={id:'import-'+'5'.repeat(32),name:'Background chair',kind:'furniture',model:'original.gltf',thumbnail:'preview.png',files:{'original.gltf':true},lods:[]};
const queuedDelete={...imported,id:'import-'+'6'.repeat(32),name:'Delete queued',files:{...imported.files},lods:[]};
const vertices=new Float32Array([0,0,0,1,0,0,0,1,0]);
const originalModel={asset:{version:'2.0'},scene:0,scenes:[{nodes:[0]}],nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0}}]}],
 buffers:[{uri:'data:application/octet-stream;base64,'+Buffer.from(vertices.buffer).toString('base64'),byteLength:36}],
 bufferViews:[{buffer:0,byteLength:36}],accessors:[{bufferView:0,componentType:5126,count:3,type:'VEC3',min:[0,0,0],max:[1,1,0]}]};
globalThis.ProgressEvent=class{constructor(type,values){Object.assign(this,values);}};
globalThis.FileReader=class{
 readAsArrayBuffer(blob){blob.arrayBuffer().then(value=>{this.result=value;this.onloadend?.();});}
 readAsDataURL(blob){blob.arrayBuffer().then(value=>{this.result='data:'+blob.type+';base64,'+Buffer.from(value).toString('base64');this.onloadend?.();});}
};
window.location={href:'http://house.test/house/editor'};
let releaseOriginal,originalRequested=false,derivedName,derivedCount=0,deleted=false,deletedLoads=0;
const originalGate=new Promise(resolve=>{releaseOriginal=resolve;});
let fetches = 0;
let householdAdded=false;
const householdMaterial={id:'material-returned',name:'Returned stone',source:'user',revision:2,
 maps:{base_color:'maps/returned.jpg'},params:{tint:'#123456',roughness:.6}};
const nativeFetch=globalThis.fetch;
globalThis.fetch = async (input,options={}) => {
 const url=typeof input==='string'?input:input.url,json=value=>new Response(JSON.stringify(value));
 if(url.startsWith('data:'))return nativeFetch(input);
 if(url.endsWith('/materials'))return json({revision:7,materials:[finish,latticeFinish,...(householdAdded?[householdMaterial]:[])]});
 if(url.endsWith('/materials/'+householdMaterial.id))return json(householdMaterial);
 if(url.endsWith('/library')){fetches++;return json({materials:[{id:'duplicate-preset',name:'Dropped preset',color:'#ffffff'}],items:[chair],imports:[{...imported},...(deleted?[]:[queuedDelete])]});}
 if(url.endsWith('/import-settings'))return json({limit_mb:50,unpacked_limit_mb:200});
 if(url.endsWith('/imports'))return json([imported,...(deleted?[]:[queuedDelete])]);
 if(url.endsWith('/original.gltf')){if(url.includes(queuedDelete.id))deletedLoads++;originalRequested=true;await originalGate;return json(originalModel);}
 if(url.endsWith('/imports/uploads')){derivedName=JSON.parse(options.body).lod;return json({upload_id:'background',chunk_bytes:4194304});}
 if(url.endsWith('/background/0'))return json({});
 if(url.endsWith('/background/finish')){
  derivedCount++;imported.lods.push({name:derivedName});imported.files[derivedName]=true;
  // Metadata can arrive with a background completion too.
  imported.name='Ready chair';return json(imported);
 }
 if(url.endsWith('/imports/'+imported.id)&&options.method==='PATCH'){Object.assign(imported,JSON.parse(options.body));return json(imported);}
 if(url.endsWith('/imports/'+imported.id)&&options.method==='DELETE')return json({});
 if(url.endsWith('/imports/'+queuedDelete.id)&&options.method==='DELETE'){deleted=true;return json({});}
 throw new Error('unexpected library request '+url);
};
const ops = [], op = async operation => {ops.push(operation);};
const abort = new AbortController(), host = new Element(), view = await mountTwin(host,{plan:flat,kit,tier:'high',preserveCamera:true});
let library;
const tools = createSceneTools({view,getPlan:()=>flat,getModel:()=>flat,getKit:()=>kit,getSheets:()=>({}),op,edit:op,
  panel:{clearSelection(){},focusSelection(){}},canEdit:()=>true,signal:abort.signal,siteHits:(x,y)=>library?.siteHits(x,y)||[]});
library = createLibrary({view,kit,getPlan:()=>flat,tools,op,canEdit:()=>true,signal:abort.signal});
tools.delegate({pointerDown:library.pointerDown,pointerMove:library.pointerMove,pointerUp:library.pointerUp,selectionChanged:library.refresh});
let passed=0;const ok = label => {passed++;console.log('  ok '+label);};
const record = {kind:'wall',piece:front,building:b};
assert.ok(materialLines(record,flat,kit).some(l=>l.text.endsWith(', from the building')));
front.faces={right:{id:finish.id,color:finish.color}};
assert.equal(materialLines(record,flat,kit).filter(l=>l.clear).length,1);
assert.equal(materialLines(record,flat,kit).find(l=>l.clear).text,'Red brick 03, set here');
tools.select({pieceId:front.id,buildingId:b.id});
const clear=descendants(doc.getElementById('piece-card')).find(n=>n.textContent==='Clear');clear.dispatchEvent(new Event('click'));
await new Promise(r=>setTimeout(r,0));assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{wall:front.id,side:'right'},material:null});
delete front.faces;
const level=b.levels.find(l=>l.id===front.level);level.materials={siding:{id:'level_finish',color:'#334455'}};
assert.ok(materialLines(record,flat,kit).some(l=>l.text==='Level finish, from the level'));delete level.materials;
const inside=wallFace(b,front,'left');assert.equal(inside.room.id,room.id);
room.wall_material={id:'room_finish',color:'#445566'};
assert.ok(materialLines(record,flat,kit).some(l=>l.text==='Room finish, from the room'));delete room.wall_material;
assert.deepEqual(surfaceOperation({building:b,piece:front,kind:'wall',side:'right',room,role:'siding'},'room',finish).target,{room:room.id,surface:'walls'});
ok('real card Clear posts once; material source follows face, room, level and building');

const world = p => {const a=(b.rotation||0)*Math.PI/180,pos=b.position||[0,0];return new THREE.Vector3(
  (Math.cos(a)*p[0]-Math.sin(a)*p[1]+pos[0])*.3048,(p[2]+(b.base||0))*.3048,-(Math.sin(a)*p[0]+Math.cos(a)*p[1]+pos[1])*.3048);};
const look = (eye,target) => view.setCameraState({position:world(eye).toArray(),target:world(target).toArray()});
const pixel = p => {const v=world(p).project(view.camera);return [(v.x+1)*720,(1-v.y)*450];};
const event = (type,x,y) => {const e=new Event(type);Object.assign(e,{pointerId:1,button:0,clientX:x,clientY:y});return e;};
const settle = async()=>{for(let i=0;i<10;i++)await new Promise(r=>setTimeout(r,0));};
doc.elementFromPoint=()=>view.renderer3.domElement;
doc.getElementById('editor-scene').parentElement=new Element();
const browse = async name => {panel.querySelectorAll('[data-library-tab]').find(n=>n.dataset.libraryTab===name).dispatchEvent(new Event('click'));await settle();};
doc.getElementById('rail-library').dispatchEvent(new Event('click'));await settle();
assert.equal(fetches,1);
const materialButtons=()=>descendants(doc.getElementById('library-entries')).filter(n=>n.dataset.material);
assert.ok(materialButtons().some(n=>n.dataset.material==='lattice'));
assert.ok(!materialButtons().some(n=>n.dataset.material==='duplicate-preset'));
assert.equal(materialButtons().find(n=>n.dataset.material===finish.id).children[0].src,finish.thumbnail_url);
const latticeTile=materialButtons().find(n=>n.dataset.material==='lattice');latticeTile.click();await settle();
assert.equal(library.selected().thumb,latticeTile.children[0].src,'generated previews reach the slot selection metadata');
materialButtons().find(n=>n.dataset.material===finish.id).click();
const editLink=actionBar().find(n=>n.tag==='a'&&n.href.endsWith('material='+finish.id));
assert.equal(editLink.textContent,'Edit in Library');assert.equal(editLink.target,'_blank');assert.equal(editLink.rel,'noopener');
assert.ok(previewMaterials.some(m=>m.alphaMap?.isDataTexture&&m.alphaTest===.5&&m.side===THREE.DoubleSide),'Library thumbnail uses procedural lattice definition');
ok('Lattice appears in the Library and its real thumbnail uses the generated cutout');
const drop = async point => {
  const thumb=descendants(doc.getElementById('library-entries')).find(n=>n.dataset.item || n.dataset.material);thumb.dispatchEvent(event('pointerdown',120,150));
  const [x,y]=pixel(point);doc.dispatchEvent(event('pointerup',x,y));await settle();
};
tools.select({pieceId:room.id,buildingId:b.id});while(!view.ready)await settle();
look([16.9,-25,6.5],[16.9,0,5.5]);await drop([16.9,0,5.5]);
const chooser=descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser');
assert.ok(chooser,'real pointer drop opens the chooser');
assert.deepEqual(chooser.children.map(n=>n.textContent),['This wall face','This room','This floor','The whole building','Cancel']);
chooser.children[0].dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{wall:front.id,side:'right'},material:{id:finish.id}});
await drop([16.9,0,5.5]);
const floorChooser=descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser');
floorChooser.children[2].dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{level:front.level,role:'siding'},material:{id:finish.id}});
assert.equal(doc.getElementById('library-status').textContent,'Drag a thumbnail onto the house or yard.');
ok('real thumbnail pointer drop resolves the rotated outside face and chosen material scope');
await browse('items');look([15.5,9,90],[15.5,9,0]);await drop([8,8,0]);
const added=ops.pop();assert.equal(added.op,'add_item');assert.equal(added.host.floor,room.id);
const xs=room.polygon.map(p=>p[0]),ys=room.polygon.map(p=>p[1]);
assert.ok(Math.abs(Math.min(...xs)+added.host.u*(Math.max(...xs)-Math.min(...xs))-8)<.1);
assert.ok(Math.abs(Math.min(...ys)+added.host.v*(Math.max(...ys)-Math.min(...ys))-8)<.1);
await browse('materials');await browse('items');assert.equal(fetches,1);
ok('floor drop posts a hosted item with room fractions; browsing reuses its catalog');
const equipment=doc.getElementById('library-entries').children.filter(n=>n.dataset.equipment);
assert.deepEqual(equipment.map(n=>n.getAttribute('aria-label')),['Meter','Electric panel','Charger','Parking spot']);
assert.ok(equipment.every(n=>n.children.some(c=>c.tag==='svg')));
let pickedEquipment=null;doc.getElementById('rail-add-charger').addEventListener('click',()=>{pickedEquipment='charger';});
equipment[2].click();assert.equal(pickedEquipment,'charger');
ok('equipment library shows four icons and invokes the charger placement tool');

// Complete a real background import while a person holds a library thumbnail.
// Both metadata updates and a requested full browse must preserve that node.
for(let i=0;i<1000&&!originalRequested;i++)await new Promise(r=>setTimeout(r,2));
assert.ok(originalRequested,'background job loads the existing original');
const grid=doc.getElementById('library-entries'),dragged=grid.children.find(n=>n.dataset.item===imported.id);
const unrelated=grid.children.find(n=>n.dataset.item===chair.id);
grid.children.find(n=>n.dataset.item===queuedDelete.id).click();
actionBar().find(n=>n.textContent==='Delete Delete queued').click();await settle();
assert.equal(deleted,true);assert.ok(!grid.children.some(n=>n.dataset.item===queuedDelete.id));
dragged.click();dragged.dispatchEvent(event('pointerdown',120,150));
releaseOriginal();
for(let i=0;i<1000&&derivedCount<2;i++)await new Promise(r=>setTimeout(r,2));
await settle();assert.equal(derivedCount,2,'real background exporter uploads both versions');
assert.equal(deletedLoads,0,'library Delete removes a pending generation job before it loads');
assert.equal(dragged.parentElement,grid,'background metadata keeps the dragged thumbnail attached');
assert.equal(unrelated.parentElement,grid,'unrelated thumbnails stay attached too');
assert.equal(grid.children.find(n=>n.dataset.item===imported.id),dragged);
assert.equal(dragged.getAttribute('aria-label'),'Ready chair');
assert.equal(dragged.children[1].textContent,'Ready chair');
assert.ok(actionBar().some(n=>n.textContent==='Rename Ready chair'));
doc.getElementById('library-search').value='Lounge';doc.getElementById('library-search').dispatchEvent(new Event('input'));
await settle();assert.equal(dragged.parentElement,grid,'full browse is deferred during drag');
const [dropX,dropY]=pixel([8,8,0]);doc.dispatchEvent(event('pointerup',dropX,dropY));await settle();
const importedDrop=ops.pop();assert.equal(importedDrop.op,'add_item');assert.equal(importedDrop.asset,imported.id);
assert.equal(importedDrop.object_kind,'furniture');assert.equal(importedDrop.host.floor,room.id);
assert.equal(dragged.parentElement,null,'deferred search refresh runs after the drop');
doc.getElementById('library-search').value='';doc.getElementById('library-search').dispatchEvent(new Event('input'));await settle();
const renamed=grid.children.find(n=>n.dataset.item===imported.id),kept=grid.children.find(n=>n.dataset.item===chair.id);
window.promptInput=async()=> 'Renamed chair';
if(renamed.getAttribute('aria-pressed')!=='true')renamed.click();
actionBar().find(n=>n.textContent==='Rename Ready chair').click();await settle();
assert.equal(renamed.parentElement,grid);assert.equal(renamed.children[1].textContent,'Renamed chair');assert.equal(kept.parentElement,grid);
renamed.dispatchEvent(event('pointerdown',120,150));
doc.getElementById('library-search').dispatchEvent(new Event('input'));await settle();
doc.dispatchEvent(event('pointercancel',120,150));await settle();assert.equal(renamed.parentElement,null,'cancel flushes a deferred browse');
ok('background LOD metadata and rename update in place; a deferred browse preserves the drag through placement or cancel');

tools.select(null);while(!view.ready)await settle();
const tree=flat.site.planting.find(p=>p.id==='cmp-tree-1'),original=[...tree.at];
const lot=p=>new THREE.Vector3(p[0]*.3048,p[2]*.3048,-p[1]*.3048);
view.setCameraState({position:lot([original[0],original[1]-.01,300]).toArray(),target:lot([...original,0]).toArray()});
const screen=p=>{const v=lot([...p,0]).project(view.camera);return [(v.x+1)*720,(1-v.y)*450];};
const start=screen(original),end=screen([96,75]),canvas=view.renderer3.domElement;
canvas.dispatchEvent(event('pointerdown',...start));doc.dispatchEvent(event('pointerup',...start));
assert.equal(tools.selection().kind,'planting');assert.equal(tools.selection().id,tree.id);
canvas.dispatchEvent(event('pointerdown',...start));canvas.dispatchEvent(event('pointermove',...end));doc.dispatchEvent(event('pointerup',...end));await settle();
assert.equal(ops.length,0,'Select-tool body drag navigates without moving the tree');
assert.equal(tools.selection().id,tree.id);assert.deepEqual(tree.at,original);assert.equal(view.controls.enabled,true);
const del=descendants(doc.getElementById('piece-card')).find(n=>n.textContent==='Delete');del.dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'delete_site_item',list:'planting',index:flat.site.planting.indexOf(tree)});
ok('canvas click selects a yard tree, Select-tool body drag navigates, and its card Delete uses the site operation');
// A keyboard tile activation selects; only the row applies. The 3D drop
// chooser above still proves the full scope list and exact operation payload.
const {createCards} = await import(file('static/twin/editor/cards.js'));
const cards = createCards({getPlan:()=>flat,getKit:()=>kit,getLabel:()=>'the piece',edit:op,op,canEdit:()=>true,
  select(){},ask(){},library});
const card = () => descendants(doc.getElementById('piece-card'));
const labelled = text => card().find(n=>n.tag==='label'&&n.textContent===text);
panel.hidden=true;
cards.draw({pieceId:front.id,buildingId:b.id});
await browse('materials');library.select(null);
const rows=card().filter(n=>n.dataset.librarySlot);
assert.equal(rows.length,2,'each face has one shared row');
const outer=rows.find(n=>n.dataset.librarySlot==='Outside');
panel.hidden=true;descendants(outer).find(n=>n.dataset.slotSwatch!==undefined).dispatchEvent(new Event('click'));await settle();
assert.equal(panel.hidden,false,'the current swatch reveals the Library');
const thumb=materialButtons()[0];assert.equal(thumb.tag,'button');
thumb.dispatchEvent(new Event('click'));await settle();
assert.equal(ops.length,0,'selecting never applies');
const use=descendants(outer).find(n=>n.dataset.slotUse!==undefined);
assert.equal(use.disabled,false);use.dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),surfaceOperation(materialLines({kind:'wall',piece:front,building:b},flat,kit).find(l=>l.label==='Outside').surface,'face',finish));
assert.equal(descendants(doc.getElementById('editor-scene').parentElement).find(n=>n.id==='material-chooser'),undefined);
ok('a keyboard tile selection enables the face row and Use preserves the surface operation');

// Final wave I4: a line from the building or the floor can be cleared there.
b.materials={...(b.materials||{}),siding:{id:'building_finish',color:'#223344'}};
cards.draw(null);cards.draw({pieceId:front.id,buildingId:b.id});
const outside = () => descendants(card().find(n=>n.dataset.librarySlot==='Outside'));
outside().find(n=>n.textContent==='Clear for the building').dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{building:b.id,role:'siding'},material:null});
const floor=b.levels.find(l=>l.id===front.level);floor.materials={siding:{id:'floor_finish',color:'#556677'}};
cards.draw(null);cards.draw({pieceId:front.id,buildingId:b.id});
assert.ok(!outside().some(n=>n.textContent==='Clear for the building'));
outside().find(n=>n.textContent==='Clear for this floor').dispatchEvent(new Event('click'));await settle();
assert.deepEqual(ops.pop(),{op:'set_material',building:b.id,target:{level:floor.id,role:'siding'},material:null});
delete floor.materials;
ok('a building or floor line clears that role from the card');

// Final wave I4: an item's card turns and sizes it; anchors and items set their offset.
b.items=[...(b.items||[]),{id:'item:test',asset:chair.id,host:{floor:room.id,u:.5,v:.5},rotation:0,scale:1,state:'settled'}];
b.anchors=[...(b.anchors||[]),{id:'anchor:test',kind:'switch',host:{wall:front.id,side:'left',at:2,z:4},offset:0,state:'settled'}];
const type = async (label,text) => {const input=labelled(label).children[0];input.value=text;input.dispatchEvent(new Event('change'));await settle();};
cards.draw({pieceId:'item:test',buildingId:b.id});
assert.equal(labelled('Size').children[0].value,'100');assert.equal(labelled('Turn').children[0].value,'0');
await type('Size','150');assert.deepEqual(ops.pop(),{op:'set',building:b.id,id:'item:test',field:'scale',value:1.5});
await type('Turn','90');assert.deepEqual(ops.pop(),{op:'set',building:b.id,id:'item:test',field:'rotation',value:90});
await type('Distance from surface',`1'-0"`);assert.deepEqual(ops.pop(),{op:'move_hosted',building:b.id,id:'item:test',offset:1});
cards.draw({pieceId:'anchor:test',buildingId:b.id});
assert.ok(labelled('Distance from surface')&&!labelled('Turn')&&!labelled('Size'));
await type('Distance from surface','3"');assert.deepEqual(ops.pop(),{op:'move_hosted',building:b.id,id:'anchor:test',offset:.25});
ok('item cards carry Turn and Size; anchor and item cards carry Distance from surface');
householdAdded=true;window.dispatchEvent(new Event('focus'));await settle();assert.equal(fetches,2,'returning from the Library rereads the catalogue');
assert.ok(materialButtons().some(n=>n.dataset.material===finish.id));
const returned=materialButtons().find(n=>n.dataset.material===householdMaterial.id);assert.ok(returned);
assert.equal(returned.children[0].src,'../api/house/twin/materials/material-returned/maps/returned.jpg');
assert.equal(kit.manifest[householdMaterial.id].revision,2);assert.equal(kit.manifest[householdMaterial.id].params.roughness,.6);
ok('returning from the Library refreshes the picker catalogue');
householdMaterial.revision=3;householdMaterial.maps.base_color='maps/replaced.jpg';
// The scene watcher has already merged the record before notifying the picker.
kit.manifest[householdMaterial.id]={kind:'material',household:true,revision:3,params:householdMaterial.params,
 maps:{base_color:'materials/'+householdMaterial.id+'/maps/replaced.jpg'}};
doc.dispatchEvent(new CustomEvent('chf-materials-changed',{detail:{ids:[householdMaterial.id]}}));await settle();
assert.equal(materialButtons().find(n=>n.dataset.material===householdMaterial.id).children[0].src,
 '../api/house/twin/materials/material-returned/maps/replaced.jpg');
ok('live catalogue notification refreshes thumbnails with an already merged manifest');
abort.abort();view.dispose();console.log(`${passed}/${passed} passed`);
"""


def run():
    code, output = run_node(REGRESSIONS, {'root': ROOT.as_posix()})
    print(output)
    if code:
        raise SystemExit(code)
    from services import twin_model_bridge, twin_model_ops, twin_library
    fixture = json.loads((ROOT / 'tests/fixtures/twin_model/household-2026-11-09.json').read_text(encoding='utf-8'))
    from services import twin_store, twin_materials, storage
    from main import house_editor_library
    from starlette.requests import Request
    twin_store.push_round(fixture, 'build')
    storage.add_member({'id': 'library-parent', 'name': 'Pat', 'role': 'parent'})
    token = storage.create_member_token('library-parent')
    request = Request({'type': 'http', 'headers': [(b'x-member-token', token.encode())], 'query_string': b''})
    catalogue = house_editor_library(request)
    code, output = run_node(SELECTIONS, {'root': ROOT.as_posix(), 'household': twin_store.current(),
        'catalogue': catalogue, 'materials': twin_materials.catalogue()['materials'], 'kit': twin_library.kit('modern_farmhouse')})
    print(output)
    if code:
        raise SystemExit(code)
    model = twin_model_bridge.assemble(fixture)[0]
    # A library plant must be drawable and survive both normalize and compose.
    from services import twin_compose
    for asset, kind in [('Bush 1', 'shrub'), ('Pine Medium', 'tree')]:
        changed, _ = twin_model_ops.apply(model, {'op': 'add_site_item', 'list': 'planting', 'asset': asset, 'at': [20, 125]})
        flat = twin_model_bridge.flatten(changed)
        plant = flat['site']['planting'][-1]
        assert plant['preset'] == asset and plant['kind'] == kind and plant['height'] > 0 and plant['src']['person']
        rebuilt = twin_compose.compose(flat, twin_library.kit('modern_farmhouse'), seed=1)[0]
        assert any(p['id'] == plant['id'] for p in rebuilt['site']['planting'])
    print('  ok library plants carry drawable metadata and survive composition')
    if not shutil.which('node'):
        raise RuntimeError('Node is required')
    kit = twin_library.kit('modern_farmhouse')
    kit['manifest'] = {}
    with tempfile.TemporaryDirectory(prefix='library_events_') as directory:
        driver, data = Path(directory) / 'driver.mjs', Path(directory) / 'input.json'
        driver.write_text(DRIVER, encoding='utf-8')
        data.write_text(json.dumps({'root': ROOT.as_posix(), 'flat': twin_model_bridge.flatten(model), 'kit': kit}), encoding='utf-8')
        result = subprocess.run([shutil.which('node'), str(driver), str(data)], capture_output=True, text=True, timeout=60)
        print(result.stdout, end='')
        if result.returncode:
            raise AssertionError(result.stderr)


if __name__ == '__main__':
    run()
