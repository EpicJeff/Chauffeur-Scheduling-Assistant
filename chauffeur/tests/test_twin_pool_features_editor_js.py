"""Mounted pool card -> shared terrain drawing -> feature fields and confirm delete."""
import json
from pathlib import Path
import sys
from twin_editor_dom import PRELUDE, run_node

ROOT = Path(__file__).resolve().parents[1]
DRIVER = PRELUDE + r"""
const THREE=await import(three);
Element.prototype.select=function(){this.selected=true;};
const {mountTwin}=await import(file('static/twin/twin_view.js'));
const {createSceneTools}=await import(file('static/twin/editor/scene_tools.js'));
const {createTerrainTools}=await import(file('static/twin/editor/terrain_tools.js'));
const {transformShape}=await import(file('static/twin/editor/site_shapes.js'));
const {yardRoomFeatures}=await import(file('static/twin/editor/site_shape_shelf.js'));
const plan={buildings:[],materials:{},site:{lot:[[0,0],[40,0],[40,40],[0,40]],terraces:[],pool:{id:'pool',polygon:[[0,0],[30,0],[30,20],[0,20]],features:[]}}};
const shell=document.createElement('div');shell.className='editor-shell';document.body.append(shell);
const host=document.createElement('div');shell.append(host);
const view=await mountTwin(host,{plan,kit:input.kit,tier:'low',bake:false});
view.setCameraState({position:[15*.3048,80*.3048,-9.999*.3048],target:[15*.3048,0,-10*.3048]});
const abort=new AbortController(),operations=[],errors=[];let writable=true,confirm=true,confirms=0;
window.showGlobalAlert=text=>errors.push(text);
window.promptConfirm=async(...args)=>{confirms++;assert.match(args[0],/Delete (spa|steps|tanning ledge)/);return confirm;};
globalThis.fetch=async url=>new Response(JSON.stringify({materials:[{id:'red_brick_03',name:'Red brick',color:'#aa3322'}],items:[]}),{status:200,headers:{'Content-Type':'application/json'}});
const defaults={ledge:{depth_in:10},steps:{treads:3,entry_edge:0},spa:{mode:'raised',raise_in:12,depth_in:36,spillover:true}};
const op=async operation=>{
 operations.push(operation);
 if(operation.op==='add_pool_feature'){const {op,...f}=operation;plan.site.pool.features.push({...defaults[f.kind],...f,id:'f'+operations.length});}
 else if(operation.op==='update_pool_feature'){const {op,id,...change}=operation;const f=plan.site.pool.features.find(f=>f.id===id);if(change.materials)change.materials={...f.materials,...change.materials};Object.assign(f,change);}
 else if(operation.op==='delete_pool_feature')plan.site.pool.features=plan.site.pool.features.filter(f=>f.id!==operation.id);
 else if(operation.op==='make_yard_room'){const f=plan.site.pool.features.find(f=>f.id===operation.feature);plan.site.yard_rooms=[{id:'spa-room',name:'Spa',polygon:f.polygon,feature:{list:'pool',id:'pool',feature:f.id}}];}
};
let terrain;
const tools=createSceneTools({view,getPlan:()=>plan,getModel:()=>plan,getKit:()=>input.kit,getSheets:()=>({}),edit:op,op,
 panel:{clearSelection(){},focusSelection(){}},canEdit:()=>writable,signal:abort.signal,onDrawFeature:kind=>terrain.startDrawing(kind)});
terrain=createTerrainTools({view,tools,getPlan:()=>plan,op,canEdit:()=>writable,signal:abort.signal});
const card=document.getElementById('piece-card'),drawCard=document.getElementById('terrain-card');
const settle=async()=>{await new Promise(r=>setTimeout(r,10));assert.deepEqual(errors,[]);};
const button=(parent,text)=>{const b=parent.querySelectorAll('button').find(b=>b.textContent===text);assert.ok(b,text);return b;};
const row=id=>card.querySelector(`[data-pool-feature="${id}"]`);
async function change(parent,label,value){const input=parent.querySelector(`[aria-label="${label}"]`);assert.ok(input,label);input.value=String(value);fire(input,'change');await settle();}
const event=p=>{const v=new THREE.Vector3(p[0]*.3048,0,-p[1]*.3048).project(view.camera),r=view.renderer3.domElement.getBoundingClientRect();return {button:0,pointerId:1,clientX:r.left+(v.x+1)*r.width/2,clientY:r.top+(1-v.y)*r.height/2};};
await test('pool card starts each polygon tool and returns to its feature rows after one edit',async()=>{
 for(const [kind,label,poly] of [['ledge','tanning ledge',[[1,0],[5,0],[5,4],[1,4]]],['steps','steps',[[10,0],[14,0],[14,4],[10,4]]],['spa','spa',[[26,4],[34,4],[34,12],[26,12]]]]){
  tools.select({kind:'pool',id:'pool'});click(button(card,'Add '+label));assert.ok(!drawCard.hidden);assert.ok(textOf(drawCard).includes('Draw'));
  const count=operations.length;
  for(const p of poly){assert.ok(terrain.pointerDown(event(p)));terrain.pointerUp(event(p),false);}
  assert.equal(operations.length,count,'drawing corners is not history');
  click(button(drawCard,'Finish'));await settle();assert.equal(operations.length,count+1);
  assert.equal(operations.at(-1).op,'add_pool_feature');assert.equal(operations.at(-1).kind,kind);
  assert.ok(drawCard.hidden);const f=plan.site.pool.features.at(-1);assert.ok(row(f.id));
  operations.at(-1).polygon.forEach((p,i)=>p.forEach((v,j)=>assert.ok(Math.abs(v-poly[i][j])<1e-5)));
 }
 assert.equal(card.querySelectorAll('[data-pool-feature]').length,3);
});
await test('rows save ledge, steps and spa properties, polygons, Library slots and room',async()=>{
 const [ledge,steps,spa]=plan.site.pool.features;
 await change(row(ledge.id),'Water depth (in)',14);assert.equal(operations.at(-1).depth_in,14);
 await change(row(steps.id),'Treads',5);assert.equal(operations.at(-1).treads,5);
 await change(row(steps.id),'Entry edge',2);assert.equal(operations.at(-1).entry_edge,2);
 await change(row(spa.id),'Water depth (in)',42);await change(row(spa.id),'Raise above deck (in)',18);
 await change(row(spa.id),'Spillover','no');assert.equal(operations.at(-1).spillover,false);
 await change(row(spa.id),'Mode','flush');assert.ok(!row(spa.id).querySelector('[aria-label="Raise above deck (in)"]'));
 await change(row(spa.id),'Mode','raised');assert.equal(spa.raise_in,18);
 await change(row(ledge.id),'Point 1 X (ft)',2);assert.equal(operations.at(-1).polygon[0][0],2);
 const count=operations.length;
 click(row(spa.id).querySelector('[aria-label="Change the wall material"]'));await settle();
 click(row(spa.id).querySelector('[data-material="red_brick_03"]'));await settle();
 assert.equal(operations.length,count+1);assert.equal(operations.at(-1).materials.wall.id,'red_brick_03');
 for(const part of ['Coping','Interior','Wall'])assert.ok(row(spa.id).querySelector(`[data-material-slot="${part}"]`));
 click(button(row(spa.id),'Make this a room'));await settle();assert.deepEqual(operations.at(-1),{op:'make_yard_room',list:'pool',feature:spa.id});
 assert.equal(plan.site.yard_rooms[0].name,'Spa');
 assert.equal(yardRoomFeatures(plan,plan.site.yard_rooms[0]).length,1);
 // Pool transforms carry the children's lot coordinates with them.
 const moved=transformShape(plan.site.pool,{centre:[25,20]});assert.equal(moved.features.length,3);
 assert.notDeepEqual(moved.features[0].polygon,ledge.polygon);
});
await test('delete needs the shared confirmation; cancellation and read-only save nothing',async()=>{
 tools.select({kind:'pool',id:'pool'});const spa=plan.site.pool.features.find(f=>f.kind==='spa'),count=operations.length;
 confirm=false;click(button(row(spa.id),'Delete'));await settle();assert.equal(operations.length,count);assert.equal(confirms,1);
 confirm=true;click(button(row(spa.id),'Delete'));await settle();assert.equal(operations.length,count+1);assert.equal(confirms,2);assert.ok(!row(spa.id));
 assert.equal(yardRoomFeatures(plan,plan.site.yard_rooms[0]).length,0,'a deleted spa is never replaced by its parent as the source');
 writable=false;tools.refreshCard();
 for(const b of card.querySelectorAll('button').filter(b=>/^Add |^Delete$/.test(b.textContent)))assert.equal(b.disabled,true);
 const before=operations.length;click(button(card,'Add spa'));await settle();assert.equal(operations.length,before);
});
abort.abort();view.dispose();finish();
"""

if __name__ == '__main__':
    kit = json.loads((ROOT / 'twin_kits/modern_farmhouse.json').read_text(encoding='utf-8'))
    code, output = run_node(DRIVER, {'root': ROOT.as_posix(), 'kit': kit})
    print(output)
    sys.exit(code or 0)
